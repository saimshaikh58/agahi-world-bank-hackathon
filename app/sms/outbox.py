"""Outbox: queued -> sending -> sent -> delivered | failed | expired. Idempotency keys, retries with backoff."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app import db, events
from app.config import settings
from app.core.sms import is_gsm7, sanitise, sms_stats
from app.sms.android_gateway import AndroidGatewayProvider
from app.sms.base import SmsProvider
from app.sms.mock import MockProvider
from app.sms.twilio import TwilioProvider
from app.util import now, now_iso

log = logging.getLogger("agahi.outbox")
MAX_ATTEMPTS = 3
BASE_BACKOFF_S = 5
EXPIRE_HOURS = 24
PROVIDERS = {"mock": MockProvider, "android_gateway": AndroidGatewayProvider, "twilio": TwilioProvider}
_provider: SmsProvider | None = None


def provider() -> SmsProvider:
    """The configured provider (singleton)."""
    global _provider
    if _provider is None:
        _provider = PROVIDERS.get(settings.sms_provider, MockProvider)(settings)
    return _provider


def set_provider(p: SmsProvider) -> None:
    """Swap provider (tests)."""
    global _provider
    _provider = p


def enqueue(phone: str, text: str, kind: str = "reply", idem: str | None = None, demo: bool = False) -> int:
    """Queue one message. Same idempotency key -> same row (no double send)."""
    if idem:
        r = db.q1("SELECT id FROM outbox WHERE idempotency_key=?", (idem,))
        if r:
            return r["id"]
    clean = sanitise(text)
    body = clean if is_gsm7(clean) else text
    st = sms_stats(body)
    return db.x("INSERT INTO outbox(created_at,phone,text,kind,status,attempts,next_attempt_at,idempotency_key,provider,"
                "encoding,segments,cost,updated_at,demo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_iso(), phone, body, kind, "queued", 0, now_iso(), idem, provider().name, st["encoding"],
                 st["segments"], st["segments"] * settings.sms_cost, now_iso(), int(demo)))


def process_once(limit: int = 20) -> int:
    """Send due messages once. Returns number processed."""
    t = now()
    db.x("UPDATE outbox SET status='expired', updated_at=? WHERE status='queued' AND created_at < ?",
         (now_iso(), (t - timedelta(hours=EXPIRE_HOURS)).replace(microsecond=0).isoformat()))
    due = db.q("SELECT * FROM outbox WHERE status='queued' AND next_attempt_at <= ? ORDER BY id LIMIT ?",
               (t.replace(microsecond=0).isoformat(), limit))
    sent = 0
    for m in due:
        with db.connect() as c:  # claim the row; another worker may have taken it already
            claimed = c.execute("UPDATE outbox SET status='sending', updated_at=? WHERE id=? AND status='queued'",
                                (now_iso(), m["id"])).rowcount
        if not claimed:
            continue
        sent += 1
        res = provider().send(m["phone"], m["text"])
        attempts = m["attempts"] + 1
        if res.ok:
            status = "delivered" if res.delivered else "sent"
            db.x("UPDATE outbox SET status=?, attempts=?, provider_msg_id=?, error=NULL, updated_at=? WHERE id=?",
                 (status, attempts, res.provider_msg_id, now_iso(), m["id"]))
            if m["kind"] != "reply":
                _log_out(m)
        elif attempts >= MAX_ATTEMPTS:
            db.x("UPDATE outbox SET status='failed', attempts=?, error=?, updated_at=? WHERE id=?",
                 (attempts, res.error, now_iso(), m["id"]))
        else:
            nxt = (t + timedelta(seconds=BASE_BACKOFF_S * 2 ** (attempts - 1))).replace(microsecond=0).isoformat()
            db.x("UPDATE outbox SET status='queued', attempts=?, error=?, next_attempt_at=?, updated_at=? WHERE id=?",
                 (attempts, res.error, nxt, now_iso(), m["id"]))
    return sent


def _log_out(m: dict) -> None:
    """Pushed messages (alerts, broadcasts, operator replies) appear in the conversation thread."""
    f = db.q1("SELECT lang, location FROM farmers WHERE phone=?", (m["phone"],)) or {}
    db.x("INSERT INTO messages(ts,phone,direction,channel,text,lang,intent,segments,encoding,chars,demo,location) "
         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (now_iso(), m["phone"], "out", m["kind"], m["text"], f.get("lang"),
                                             m["kind"].upper(), m["segments"], m["encoding"], len(m["text"]),
                                             m["demo"], f.get("location")))
    events.publish("message", {"phone": m["phone"], "direction": "out", "text": m["text"], "intent": m["kind"].upper(),
                               "ts": now_iso()})


def record_inline(phone: str, text: str, inbound_id: str | None) -> int:
    """A reply that went back inside the webhook response (TwiML) is logged as already sent."""
    st = sms_stats(text)
    return db.x("INSERT INTO outbox(created_at,phone,text,kind,status,attempts,next_attempt_at,idempotency_key,provider,"
                "encoding,segments,cost,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_iso(), phone, text, "reply", "sent", 1, now_iso(), f"inline:{inbound_id}" if inbound_id else None,
                 provider().name, st["encoding"], st["segments"], st["segments"] * settings.sms_cost, now_iso()))


def apply_status(provider_msg_id: str, status: str, outbox_id: int | None = None) -> bool:
    """Delivery receipt. Matches by provider message id, or by our outbox id (TwiML replies)."""
    if status not in ("sent", "delivered", "failed"):
        return False
    r = db.q1("SELECT id FROM outbox WHERE provider_msg_id=?", (provider_msg_id,))
    if not r and outbox_id:
        r = db.q1("SELECT id FROM outbox WHERE id=?", (outbox_id,))
    if not r:
        return False
    db.x("UPDATE outbox SET status=?, provider_msg_id=COALESCE(provider_msg_id, ?), updated_at=? WHERE id=?",
         (status, provider_msg_id, now_iso(), r["id"]))
    return True


async def worker(stop: asyncio.Event) -> None:
    """Background loop started by the app."""
    while not stop.is_set():
        try:
            await asyncio.to_thread(process_once)
        except Exception:  # keep the worker alive
            log.exception("outbox worker error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


def funnel() -> dict:
    """Counts by status."""
    return {r["status"]: r["n"] for r in db.q("SELECT status, COUNT(*) AS n FROM outbox GROUP BY status")}

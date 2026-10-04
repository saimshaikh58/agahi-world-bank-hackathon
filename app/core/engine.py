"""The single entry point for every channel: dedupe -> compliance -> rate limit -> session -> language ->
NLU/flow -> render -> budget -> log -> SSE."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field

from app import db, events
from app.config import settings
from app.core import nlu
from app.core.data import store
from app.core.flows import Flow, FlowOut
from app.core.replies import Rendered, simple
from app.core.sms import sms_stats
from app.util import normalise_phone, now_iso

log = logging.getLogger("agahi.engine")
MAX_INBOUND_CHARS = 480
DEFAULT_LANG = "rn"
_rate_lock = threading.Lock()
_minute: dict[str, deque] = defaultdict(deque)
_day: dict[str, deque] = defaultdict(deque)
_phone_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


@dataclass
class Reply:
    """Outbound reply with full provenance."""
    text: str
    lang: str
    intent: str
    intent_confidence: float
    state_before: str
    state_after: str
    crop: str | None
    horizon: str | None
    location: str | None
    segments: int
    encoding: str
    chars: int
    latency_ms: float
    trace: dict = field(default_factory=dict)
    duplicate: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def rate_limited(phone: str) -> bool:
    """True if this phone exceeded RATE_PER_MIN or RATE_PER_DAY."""
    t = time.time()
    with _rate_lock:
        m, d = _minute[phone], _day[phone]
        while m and t - m[0] > 60:
            m.popleft()
        while d and t - d[0] > 86400:
            d.popleft()
        if len(m) >= settings.rate_per_min or len(d) >= settings.rate_per_day:
            return True
        m.append(t)
        d.append(t)
        return False


def reset_rate(phone: str | None = None) -> None:
    """Clear rate counters (tests, simulator reset)."""
    with _rate_lock:
        if phone:
            _minute.pop(phone, None)
            _day.pop(phone, None)
        else:
            _minute.clear()
            _day.clear()


def load_farmer(phone: str, demo: bool = False, ts: str | None = None) -> dict:
    """Get or create the farmer row (new numbers record consent on first inbound)."""
    f = db.q1("SELECT * FROM farmers WHERE phone=?", (phone,))
    if f:
        return f
    t = ts or now_iso()
    db.x("INSERT OR IGNORE INTO farmers(phone,lang,onboarding_state,subscribed,consent_at,created_at,last_seen,demo) "
         "VALUES(?,?,?,?,?,?,?,?)", (phone, DEFAULT_LANG, "NEW", 1, t, t, t, int(demo)))
    return db.q1("SELECT * FROM farmers WHERE phone=?", (phone,))


def load_ctx(phone: str) -> dict:
    """Session context."""
    r = db.q1("SELECT ctx_json FROM sessions WHERE phone=?", (phone,))
    try:
        return json.loads(r["ctx_json"]) if r else {"state": "NEW"}
    except ValueError:
        return {"state": "NEW"}


def save(f: dict, ctx: dict, ts: str) -> None:
    """Persist farmer + session in one short transaction."""
    with db.connect() as c:
        c.execute("UPDATE farmers SET lang=?, location=?, onboarding_state=?, subscribed=?, last_seen=? WHERE phone=?",
                  (f["lang"], f.get("location"), f["onboarding_state"], int(f["subscribed"]), ts, f["phone"]))
        c.execute("INSERT INTO sessions(phone,ctx_json,updated_at) VALUES(?,?,?) ON CONFLICT(phone) DO UPDATE SET "
                  "ctx_json=excluded.ctx_json, updated_at=excluded.updated_at", (f["phone"], json.dumps(ctx), ts))


def reset_session(phone: str) -> None:
    """Forget a number completely (simulator 'reset')."""
    with db.connect() as c:
        c.execute("DELETE FROM sessions WHERE phone=?", (phone,))
        c.execute("DELETE FROM farmers WHERE phone=?", (phone,))
        c.execute("DELETE FROM messages WHERE phone=?", (phone,))
    reset_rate(phone)


def _log_message(ts, phone, direction, channel, text, lang, intent, conf, crop, horizon, loc, state, stats,
                 latency, trace, demo, pid) -> None:
    db.x("INSERT INTO messages(ts,phone,direction,channel,text,lang,intent,confidence,crop,horizon,location,state,"
         "segments,encoding,chars,latency_ms,trace_json,demo,provider_msg_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (ts, phone, direction, channel, text, lang, intent, conf, crop, horizon, loc, state,
          stats.get("segments"), stats.get("encoding"), stats.get("chars"), latency,
          json.dumps(trace, ensure_ascii=False, default=str) if trace else None, int(demo), pid))
    events.publish("message", {"phone": phone, "direction": direction, "text": text, "intent": intent, "lang": lang,
                               "ts": ts, "demo": bool(demo)})


def handle_message(channel: str, phone: str, text: str, provider_msg_id: str | None = None, offline: bool = False,
                   demo: bool = False, ts: str | None = None) -> Reply:
    """Process one inbound message and return the reply. Never raises for bad input."""
    t0 = time.perf_counter()
    ts = ts or now_iso()
    phone = normalise_phone(phone, settings.country_code) or phone
    text = (text or "")[:MAX_INBOUND_CHARS]
    if provider_msg_id and db.q1("SELECT id FROM messages WHERE provider_msg_id=?", (provider_msg_id,)):
        return Reply("", "", "DUPLICATE", 1.0, "", "", None, None, None, 0, "GSM7", 0, 0.0,
                     {"note": "duplicate provider id"}, True)
    with _phone_locks[phone]:
        f = load_farmer(phone, demo, ts)
        ctx = load_ctx(phone)
        state_before = ctx.get("state", "NEW") if f["onboarding_state"] == "DONE" else f["onboarding_state"]
        limited = channel == "sms" and not demo and rate_limited(phone)
        _set_lang(f, text)
        sample = store().is_sample
        if limited:
            out = FlowOut(simple(f["lang"], "rate"), "RATE_LIMITED")
        else:
            try:
                out = Flow(f, ctx, offline, sample).step(text)
            except Exception:  # never let one message crash the channel
                log.exception("flow failed for %s", phone)
                out = FlowOut(simple(f["lang"], "unknown", "main"), "UNKNOWN", 0.0)
        r: Rendered = out.r
        stats = sms_stats(r.text)
        state_after = ctx.get("state", "MAIN") if f["onboarding_state"] == "DONE" else f["onboarding_state"]
        latency = round((time.perf_counter() - t0) * 1000, 2)
        trace = {"probs": out.nlu.get("probs", {}), "slots": out.nlu.get("slots", {}),
                 "normalised": out.nlu.get("normalised", nlu.normalise(text)), "rule": out.nlu.get("rule", ""),
                 "sources": r.sources, "model": r.model, "status": r.status, "dropped_parts": r.dropped,
                 "data_version": store().data_version, "model_run": store().run_id, "offline": offline,
                 "sms": stats}
        if not limited:
            save(f, ctx, ts)
        crop, horizon = ctx.get("crop"), ctx.get("horizon") if out.intent == "FORECAST" else None
        loc = f.get("location")
        _log_message(ts, phone, "in", channel, text, f["lang"], out.intent, out.confidence, crop, horizon, loc,
                     state_before, sms_stats(text), None, None, demo, provider_msg_id)
        _log_message(ts, phone, "out", channel, r.text, f["lang"], out.intent, out.confidence, crop, horizon, loc,
                     state_after, stats, latency, trace, demo, None)
    return Reply(r.text, f["lang"], out.intent, float(out.confidence), state_before, state_after, crop, horizon, loc,
                 stats["segments"], stats["encoding"], stats["chars"], latency, trace)


def _set_lang(f: dict, text: str) -> None:
    """Detect language from free text and remember it per phone."""
    s = (text or "").strip()
    if not s or s.isdigit() or len(s) < 2:
        return
    det = nlu.detect_lang(s)
    if det and det != f["lang"] and (f["onboarding_state"] == "NEW" or det == "ne"):
        f["lang"] = det

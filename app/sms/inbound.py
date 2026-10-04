"""Inbound webhook handling: verify, parse, normalise, dedupe (engine), reply; delivery receipts."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app import db
from app.config import settings
from app.core.engine import MAX_INBOUND_CHARS, handle_message
from app.sms import outbox
from app.util import normalise_phone, now_iso

log = logging.getLogger("agahi.inbound")


class SignatureError(Exception):
    """Webhook signature missing or wrong."""


@dataclass
class InboundResult:
    """What the webhook should answer: count of replies, and for inline providers the reply text."""
    queued: int
    inline_text: str | None = None
    outbox_id: int | None = None


def _log(kind: str, ok: bool, note: str, payload: dict) -> None:
    db.x("INSERT INTO webhook_log(ts,kind,ok,note,payload) VALUES(?,?,?,?,?)",
         (now_iso(), kind, int(ok), note, json.dumps(payload, ensure_ascii=False)[:2000]))


def handle_inbound(raw: bytes, headers: dict, url: str, data: dict) -> InboundResult:
    """Process an inbound webhook. Raises SignatureError."""
    p = outbox.provider()
    if not p.verify(raw, headers, url, data):
        _log("inbound", False, "bad signature (check PUBLIC_BASE_URL)", {"url": url})
        raise SignatureError("Invalid webhook signature")
    res = InboundResult(0)
    for msg in p.parse_inbound(data):
        phone = normalise_phone(msg.phone, settings.country_code)
        if not phone:
            _log("inbound", False, "bad phone", {"from": "unreadable"})
            continue
        r = handle_message("sms", phone, msg.text[:MAX_INBOUND_CHARS], provider_msg_id=msg.provider_msg_id)
        if r.duplicate:
            _log("inbound", True, "duplicate ignored", {"id": msg.provider_msg_id})
            continue
        if r.text:
            if p.reply_inline:
                res.outbox_id = outbox.record_inline(phone, r.text, msg.provider_msg_id)
                res.inline_text = r.text
            else:
                outbox.enqueue(phone, r.text, "reply", idem=f"reply:{msg.provider_msg_id}" if msg.provider_msg_id else None)
            res.queued += 1
        _log("inbound", True, f"intent {r.intent}", {"id": msg.provider_msg_id})
    return res


def handle_status(raw: bytes, headers: dict, url: str, data: dict, outbox_id: int | None = None) -> int:
    """Delivery receipts. Returns number applied. Raises SignatureError."""
    p = outbox.provider()
    if not p.verify(raw, headers, url, data):
        _log("status", False, "bad signature (check PUBLIC_BASE_URL)", {"url": url})
        raise SignatureError("Invalid webhook signature")
    n = 0
    for mid, st in p.parse_status(data):
        if outbox.apply_status(mid, st, outbox_id):
            n += 1
    _log("status", True, f"{n} receipts", {k: v for k, v in data.items() if k in ("MessageSid", "MessageStatus", "id", "status", "event")})
    return n

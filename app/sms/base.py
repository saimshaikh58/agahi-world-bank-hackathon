"""SMS provider interface. Going live = pick a provider via SMS_PROVIDER and set its env vars."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


@dataclass
class InboundMsg:
    """One inbound SMS."""
    phone: str
    text: str
    provider_msg_id: str | None


@dataclass
class SendResult:
    """Result of one send attempt."""
    ok: bool
    provider_msg_id: str | None = None
    error: str | None = None
    delivered: bool = False  # provider confirmed delivery synchronously (mock only)


class SmsProvider:
    """Base class. Subclasses implement send / parse_inbound / parse_status and may override verify."""
    name = "base"
    simulated = False
    reply_inline = False  # True: the reply goes back in the webhook HTTP response (Twilio TwiML)

    def __init__(self, settings) -> None:
        self.s = settings

    def send(self, phone: str, text: str) -> SendResult:
        raise NotImplementedError

    def parse_inbound(self, data: dict) -> list[InboundMsg]:
        raise NotImplementedError

    def parse_status(self, data: dict) -> list[tuple[str, str]]:
        """Return [(provider_msg_id, status)] with status in sent|delivered|failed."""
        raise NotImplementedError

    def verify(self, raw: bytes, headers: dict, url: str, form: dict) -> bool:
        """Default: HMAC-SHA256 hex of the raw body in X-Agahi-Signature when SMS_WEBHOOK_SECRET is set."""
        secret = self.s.sms_webhook_secret
        if not secret or not self.s.sms_verify_signature:
            return True
        sig = headers.get("x-agahi-signature", "")
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)


def sign(secret: str, raw: bytes) -> str:
    """Helper for clients/tests: compute X-Agahi-Signature."""
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

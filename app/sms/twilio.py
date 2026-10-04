"""Twilio. No SDK: plain HTTPS through app.http.
Inbound: form fields From, To, Body, MessageSid, signed with X-Twilio-Signature. We answer inside the
HTTP response as TwiML. Outbound (alerts, broadcasts, operator replies): Messages REST API with Basic auth.
Status callback: MessageSid + MessageStatus."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from xml.sax.saxutils import escape, quoteattr

from app import http
from app.sms.base import InboundMsg, SendResult, SmsProvider

API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
STATUS_MAP = {"accepted": "sent", "queued": "sent", "sending": "sent", "sent": "sent", "delivered": "delivered",
              "undelivered": "failed", "failed": "failed", "canceled": "failed"}
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


def signature(token: str, url: str, params: dict) -> str:
    """Twilio request signature: base64(HMAC-SHA1(token, url + sorted key+value pairs))."""
    payload = url + "".join(k + str(params[k]) for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()).decode()


def twiml(text: str | None, action_url: str | None = None) -> str:
    """A TwiML reply. Empty text gives an empty <Response/> (no SMS sent)."""
    if not text:
        return EMPTY_TWIML
    attrs = f" action={quoteattr(action_url)} method=\"POST\"" if action_url else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message{attrs}>{escape(text)}</Message></Response>'


class TwilioProvider(SmsProvider):
    """Uses TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER and PUBLIC_BASE_URL."""
    name = "twilio"
    reply_inline = True

    def send(self, phone: str, text: str) -> SendResult:
        if not (self.s.twilio_sid and self.s.twilio_token and self.s.twilio_from):
            return SendResult(False, None, "Twilio settings missing: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER")
        data = {"To": phone, "From": self.s.twilio_from, "Body": text}
        if self.s.public_base_url:
            data["StatusCallback"] = self.s.public_base_url + "/api/sms/status"
        try:
            code, body = http.post(API.format(sid=self.s.twilio_sid), data=data, auth=(self.s.twilio_sid, self.s.twilio_token))
        except Exception as e:  # network error -> retried by the outbox
            return SendResult(False, None, f"network: {e}")
        if code >= 300:
            try:
                msg = json.loads(body).get("message", body)
            except ValueError:
                msg = body
            return SendResult(False, None, f"Twilio HTTP {code}: {str(msg)[:160]}")
        try:
            return SendResult(True, json.loads(body).get("sid"))
        except ValueError:
            return SendResult(True, None)

    def verify(self, raw: bytes, headers: dict, url: str, form: dict) -> bool:
        if not self.s.sms_verify_signature:
            return True
        if not self.s.twilio_token:
            return False
        sent = headers.get("x-twilio-signature", "")
        return bool(sent) and hmac.compare_digest(sent, signature(self.s.twilio_token, url, form))

    def parse_inbound(self, data: dict) -> list[InboundMsg]:
        if not data.get("From"):
            return []
        return [InboundMsg(str(data["From"]), str(data.get("Body", "")), data.get("MessageSid") or data.get("SmsSid"))]

    def parse_status(self, data: dict) -> list[tuple[str, str]]:
        st = STATUS_MAP.get(str(data.get("MessageStatus") or data.get("SmsStatus") or "").lower())
        sid = data.get("MessageSid") or data.get("SmsSid")
        return [(str(sid), st)] if st and sid else []

"""Free path: an Android phone running an SMS gateway app (format of the open-source 'SMS Gateway for Android').
Outbound: POST {ANDROID_GATEWAY_URL}/message with basic auth 'user:pass' from ANDROID_GATEWAY_TOKEN.
Inbound webhook: {"event":"sms:received","payload":{"phoneNumber","message","messageId"}}.
Status webhook: {"event":"sms:sent|sms:delivered|sms:failed","payload":{"messageId"}}."""
from __future__ import annotations

import json

from app import http
from app.sms.base import InboundMsg, SendResult, SmsProvider

STATUS_MAP = {"sms:sent": "sent", "sms:delivered": "delivered", "sms:failed": "failed"}


class AndroidGatewayProvider(SmsProvider):
    """Configurable via ANDROID_GATEWAY_URL and ANDROID_GATEWAY_TOKEN."""
    name = "android_gateway"

    def send(self, phone: str, text: str) -> SendResult:
        if not self.s.android_url:
            return SendResult(False, None, "ANDROID_GATEWAY_URL not set")
        user, _, pwd = self.s.android_token.partition(":")
        try:
            code, body = http.post(self.s.android_url.rstrip("/") + "/message",
                                   json_body={"textMessage": {"text": text}, "phoneNumbers": [phone]},
                                   auth=(user, pwd) if user else None)
        except Exception as e:  # network error -> retry later
            return SendResult(False, None, f"network: {e}")
        if code >= 300:
            return SendResult(False, None, f"HTTP {code}: {body[:120]}")
        try:
            mid = json.loads(body).get("id")
        except ValueError:
            mid = None
        return SendResult(True, mid)

    def parse_inbound(self, data: dict) -> list[InboundMsg]:
        p = data.get("payload") or data
        phone = p.get("phoneNumber") or p.get("from")
        text = p.get("message") if "message" in p else p.get("text")
        if not phone or text is None:
            return []
        return [InboundMsg(str(phone), str(text), p.get("messageId") or p.get("id"))]

    def parse_status(self, data: dict) -> list[tuple[str, str]]:
        st = STATUS_MAP.get(str(data.get("event", "")))
        mid = (data.get("payload") or {}).get("messageId")
        return [(str(mid), st)] if st and mid else []

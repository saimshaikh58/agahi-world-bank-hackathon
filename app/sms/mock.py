"""Mock provider: 'delivers' to the web simulator, with simulated delivery receipts. Labelled SIMULATED."""
from __future__ import annotations

import uuid

from app.sms.base import InboundMsg, SendResult, SmsProvider


class MockProvider(SmsProvider):
    """No network. Every send succeeds unless the text contains the test marker FAILTEST."""
    name = "mock"
    simulated = True

    def send(self, phone: str, text: str) -> SendResult:
        if "FAILTEST" in text:
            return SendResult(False, None, "simulated failure")
        return SendResult(True, f"SIM-{uuid.uuid4().hex[:12]}", None, delivered=True)

    def parse_inbound(self, data: dict) -> list[InboundMsg]:
        if not data.get("from") or "text" not in data:
            return []
        return [InboundMsg(str(data["from"]), str(data["text"]), data.get("id"))]

    def parse_status(self, data: dict) -> list[tuple[str, str]]:
        if data.get("id") and data.get("status"):
            return [(str(data["id"]), str(data["status"]))]
        return []

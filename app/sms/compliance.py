"""Consent, opt-out and quiet-hours rules for anything we send without being asked (alerts, broadcasts)."""
from __future__ import annotations

from app import db
from app.util import in_quiet_hours


def can_push(farmer: dict) -> bool:
    """Alerts/broadcasts only to subscribed, onboarded, consenting farmers."""
    return bool(farmer.get("subscribed")) and farmer.get("onboarding_state") == "DONE" and bool(farmer.get("consent_at"))


def quiet_now() -> bool:
    """21:00-06:00 Asia/Kathmandu."""
    return in_quiet_hours()


def optout_count() -> int:
    """Number of unsubscribed farmers."""
    r = db.q1("SELECT COUNT(*) AS n FROM farmers WHERE subscribed=0")
    return int(r["n"]) if r else 0

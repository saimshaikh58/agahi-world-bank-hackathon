"""Small shared helpers: time, phone masking and normalisation."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

KTM = timezone(timedelta(hours=5, minutes=45), name="Asia/Kathmandu")


def now() -> datetime:
    """Current time in Asia/Kathmandu."""
    return datetime.now(KTM)


def now_iso() -> str:
    """Current Kathmandu time as ISO string (seconds)."""
    return now().replace(microsecond=0).isoformat()


def mask_phone(phone: str | None) -> str:
    """+9779812341234 -> +977-98****1234."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("977") and len(digits) > 7:
        local = digits[3:]
        return f"+977-{local[:2]}****{local[-4:]}"
    if len(digits) <= 6:
        return "****"
    return f"+{digits[:2]}****{digits[-4:]}"


def normalise_phone(raw: str, country_code: str = "977") -> str | None:
    """Return E.164 (+977...) or None if it does not look like a phone number."""
    if not raw:
        return None
    s = raw.strip()
    digits = re.sub(r"\D", "", s)
    if not digits or len(digits) < 6 or len(digits) > 15:
        return None
    if s.startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith(country_code) and len(digits) > 10:
        return "+" + digits
    return "+" + country_code + digits.lstrip("0")


def in_quiet_hours(t: datetime | None = None) -> bool:
    """Quiet hours 21:00-06:00 Asia/Kathmandu."""
    t = t or now()
    return t.hour >= 21 or t.hour < 6

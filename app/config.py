"""Single source of configuration. Reads env vars (and .env) with safe defaults."""
from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Read-only files shipped with the code (bundled data ZIP, NLU training data).
ASSETS_DIR = ROOT / "data"
# Prepared deploy files (seed database, trained models, reports) made by scripts/prepare_deploy.py.
DEPLOY_DIR = ROOT / "deploy_assets"
# Vercel (and similar serverless hosts) only allow writing to /tmp. No background threads there.
IS_SERVERLESS = bool(os.environ.get("VERCEL"))
# Where the app writes: the project folder locally, /tmp/agahi on Vercel. DATA_DIR overrides both.
_WRITE_ROOT = Path("/tmp/agahi") if IS_SERVERLESS else ROOT
DATA_DIR = Path(os.environ.get("DATA_DIR", str(_WRITE_ROOT / "data")))
# Output folders can be redirected (the test suite uses temporary folders so it never touches real results).
MODELS_DIR = Path(os.environ.get("AGAHI_MODELS_DIR", str(_WRITE_ROOT / "models")))
REPORTS_DIR = Path(os.environ.get("AGAHI_REPORTS_DIR", str(_WRITE_ROOT / "reports")))
LOGS_DIR = Path(os.environ.get("AGAHI_LOGS_DIR", str(_WRITE_ROOT / "logs")))
BUNDLE_DIR = Path(os.environ.get("AGAHI_BUNDLE_DIR", str(DATA_DIR / "bundle")))
SAMPLE_DIR = ROOT / "sample_data"
STATIC_DIR = ROOT / "app" / "static"
TEMPLATES_DIR = ROOT / "app" / "templates"
DEFAULT_ADMIN_PASSWORD = "agahi-admin"
SMS_PROVIDERS = ("mock", "android_gateway", "twilio")


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _e164(raw: str) -> str:
    """'+1 415-555 0100' -> '+14155550100'. Empty stays empty."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return "+" + digits if digits else ""


def twilio_ready(s: "Settings") -> dict:
    """Which Twilio settings are present (never the values)."""
    return {"TWILIO_ACCOUNT_SID": bool(s.twilio_sid), "TWILIO_AUTH_TOKEN": bool(s.twilio_token),
            "TWILIO_PHONE_NUMBER": bool(s.twilio_from), "PUBLIC_BASE_URL": bool(s.public_base_url)}


def _secret(admin_password: str) -> str:
    """Key that signs admin cookies and CSRF tokens. SECRET_KEY if set; otherwise derived from ADMIN_PASSWORD,
    so every server instance (including serverless ones with an empty disk) agrees on the same key."""
    env = os.environ.get("SECRET_KEY", "").strip()
    if env:
        return env
    return hashlib.sha256(("agahi-session-key:" + admin_password).encode("utf-8")).hexdigest()


@dataclass
class Settings:
    """Validated runtime settings."""
    admin_password: str
    secret_key: str
    port: int
    train_mode: str
    sms_provider: str
    sms_webhook_secret: str
    sms_cost: float
    country_code: str
    rate_per_min: int
    rate_per_day: int
    android_url: str
    android_token: str
    twilio_sid: str
    twilio_token: str
    twilio_from: str
    public_base_url: str
    sms_verify_signature: bool
    alerts_token: str
    fetch_token: str
    auto_fetch: bool
    serverless: bool
    max_upload_mb: int
    brand_primary: str
    brand_accent: str
    live_weather: bool
    db_path: Path


def load_settings() -> Settings:
    """Read env (+ .env) and return validated settings."""
    _load_dotenv(ROOT / ".env")
    mode = os.environ.get("TRAIN_MODE", "fast").strip().lower()
    provider = os.environ.get("SMS_PROVIDER", "mock").strip().lower()
    return Settings(
        admin_password=os.environ.get("ADMIN_PASSWORD", "").strip() or DEFAULT_ADMIN_PASSWORD,
        secret_key=_secret(os.environ.get("ADMIN_PASSWORD", "").strip() or DEFAULT_ADMIN_PASSWORD),
        port=_int("PORT", 8000, 1, 65535),
        train_mode=mode if mode in ("fast", "full") else "fast",
        sms_provider=provider if provider in SMS_PROVIDERS else "mock",
        sms_webhook_secret=os.environ.get("SMS_WEBHOOK_SECRET", "").strip(),
        sms_cost=_float("SMS_COST_PER_SEGMENT_NPR", 0.5),
        country_code=os.environ.get("DEFAULT_COUNTRY_CODE", "977").strip().lstrip("+") or "977",
        rate_per_min=_int("RATE_PER_MIN", 20, 1, 10000),
        rate_per_day=_int("RATE_PER_DAY", 200, 1, 100000),
        android_url=os.environ.get("ANDROID_GATEWAY_URL", "").strip(),
        android_token=os.environ.get("ANDROID_GATEWAY_TOKEN", "").strip(),
        twilio_sid=os.environ.get("TWILIO_ACCOUNT_SID", "").strip(),
        twilio_token=os.environ.get("TWILIO_AUTH_TOKEN", "").strip(),
        twilio_from=_e164(os.environ.get("TWILIO_PHONE_NUMBER", "") or os.environ.get("TWILIO_FROM", "")),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        sms_verify_signature=os.environ.get("SMS_VERIFY_SIGNATURE", "true").strip().lower() not in ("0", "false", "no"),
        alerts_token=os.environ.get("ALERTS_TOKEN", "").strip(),
        fetch_token=(os.environ.get("FETCH_TOKEN", "") or os.environ.get("CRON_SECRET", "")).strip(),
        auto_fetch=os.environ.get("AUTO_FETCH", "1").strip().lower() not in ("0", "false", "no", "off"),
        serverless=IS_SERVERLESS,
        max_upload_mb=_int("MAX_UPLOAD_MB", 60, 1, 500),
        brand_primary=os.environ.get("BRAND_PRIMARY", "").strip(),
        brand_accent=os.environ.get("BRAND_ACCENT", "").strip(),
        live_weather=os.environ.get("LIVE_WEATHER", "1").strip() not in ("0", "false", "no"),
        db_path=Path(os.environ.get("AGAHI_DB", str(DATA_DIR / "agahi.db"))),
    )


settings = load_settings()

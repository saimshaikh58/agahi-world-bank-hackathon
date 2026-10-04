"""Open-Meteo 7-day forecast (free, no key) with a 3 hour SQLite cache and 5 s timeout."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

from app import db, http
from app.config import settings
from app.util import now, now_iso

log = logging.getLogger("agahi.weather.live")
URL = "https://api.open-meteo.com/v1/forecast"
CACHE_HOURS = 3
FAIL_BACKOFF_S = 600
_last_fail: dict[str, float] = {}


def _cached(location: str, max_age_h: float) -> list[dict] | None:
    r = db.q1("SELECT fetched_at, payload FROM weather_cache WHERE location=?", (location,))
    if not r:
        return None
    age = now() - datetime.fromisoformat(r["fetched_at"])
    if age > timedelta(hours=max_age_h):
        return None
    return json.loads(r["payload"])


def reset_backoff() -> None:
    """Forget recent failures (used by tests and the system check)."""
    _last_fail.clear()


def forecast7(location: str, lat: float | None, lon: float | None, offline: bool = False) -> tuple[list[dict] | None, str]:
    """Return (days, source). source: live | cache | none. Never raises."""
    if lat is None or lon is None:
        return None, "none"
    fresh = _cached(location, CACHE_HOURS)
    if fresh:
        return fresh, "cache"
    if offline or not settings.live_weather or time.time() - _last_fail.get(location, 0) < FAIL_BACKOFF_S:
        stale = _cached(location, 24 * 7)
        return (stale, "cache") if stale else (None, "none")
    params = {"latitude": lat, "longitude": lon, "timezone": "Asia/Kathmandu", "forecast_days": 7,
              "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,wind_speed_10m_max"}
    try:
        data = http.get_json(URL, params=params)
        d = data["daily"]
        days = [{"date": d["time"][i], "rain": d["precipitation_sum"][i], "tmax": d["temperature_2m_max"][i],
                 "tmin": d["temperature_2m_min"][i], "wind": d["wind_speed_10m_max"][i]} for i in range(len(d["time"]))]
    except Exception as e:  # network down, timeout or bad payload -> caller falls back
        log.warning("Open-Meteo failed for %s: %s (using climatology for 10 min)", location, e)
        _last_fail[location] = time.time()
        stale = _cached(location, 24 * 7)
        return (stale, "cache") if stale else (None, "none")
    db.x("INSERT INTO weather_cache(location,fetched_at,payload) VALUES(?,?,?) ON CONFLICT(location) DO UPDATE SET "
         "fetched_at=excluded.fetched_at, payload=excluded.payload", (location, now_iso(), json.dumps(days)))
    return days, "live"

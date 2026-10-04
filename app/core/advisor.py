"""Sell / hold hint. Uses d7/d14 forecasts only when their status is 'reliable'; otherwise trend + weather rules.
Never claims high confidence."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.data import store
from app.weather import outlook

MOVE_PCT = 5.0
TREND_PCT = 10.0
HEAVY_RAIN_MM = 20.0


@dataclass
class Advice:
    """Advisor output."""
    action: str            # SELL_NOW | HOLD | WAIT
    confidence: str        # low | medium
    reason: str            # template key
    reason_args: dict = field(default_factory=dict)
    expected_change_pct: float | None = None
    used_forecast: str | None = None
    no_forecast: bool = True
    value_now: float | None = None


def advise(crop: str, qty: float | None, location: str, offline: bool = False) -> Advice | None:
    """Return advice for one crop at the farmer's location (None if no price data)."""
    s = store()
    p = s.price_today(crop)
    if not p:
        return None
    value = qty * p["price"] if qty else None
    wx = outlook.next7(location, offline)
    rain_tmrw = wx.get("tomorrow_rain") or 0.0
    for h in ("d7", "d14"):
        f = s.forecast(crop, h)
        if f and f["status"] == "reliable" and f["pct_change_p50"] is not None:
            pct = float(f["pct_change_p50"])
            if pct >= MOVE_PCT:
                a = Advice("HOLD", "medium", "r_fc_up", {"h": h, "pct": pct}, pct, h, False, value)
            elif pct <= -MOVE_PCT:
                a = Advice("SELL_NOW", "medium", "r_fc_down", {"h": h, "pct": pct}, pct, h, False, value)
            else:
                a = Advice("SELL_NOW", "low", "r_fc_flat", {"h": h, "pct": pct}, pct, h, False, value)
            return a
    if wx.get("method") != "climatology" and rain_tmrw >= HEAVY_RAIN_MM:
        return Advice("WAIT", "low", "r_rain", {"mm": rain_tmrw}, None, None, True, value)
    r7 = (p.get("ret7") or 0.0) * 100
    if r7 >= TREND_PCT:
        return Advice("SELL_NOW", "low", "r_up", {"pct": r7}, None, None, True, value)
    if r7 <= -TREND_PCT:
        return Advice("HOLD", "low", "r_down", {"pct": r7}, None, None, True, value)
    return Advice("SELL_NOW", "low", "r_flat", {}, None, None, True, value)

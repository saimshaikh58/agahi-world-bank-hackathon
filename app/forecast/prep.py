"""Series preparation per crop: primary variant, carried-over days as missing, short-gap fill, joins."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app import db

HORIZONS = ["d7", "d14", "d21", "d28", "m1", "m2", "m3"]
HORIZON_DAYS = {"d7": 7, "d14": 14, "d21": 21, "d28": 28, "m1": 30, "m2": 60, "m3": 90}
MONTH_HORIZONS = {"m1", "m2", "m3"}
MAX_FILL_DAYS = 3
AREA = "boundary_mean"


def target_gap(h: str) -> int:
    """Days after origin until the target is fully known (used for the embargo)."""
    return HORIZON_DAYS[h] + (3 if h in MONTH_HORIZONS else 0)


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read prices, daily_crop and area weather from the DB."""
    with db.connect() as c:
        prices = pd.read_sql_query("SELECT * FROM prices", c)
        daily = pd.read_sql_query("SELECT date, crop, arrivals_kg FROM daily_crop", c)
        weather = pd.read_sql_query("SELECT date, rain, tmax FROM weather WHERE location=?", c, params=(AREA,))
    return prices, daily, weather


def build_frame(prices: pd.DataFrame, daily: pd.DataFrame | None, weather: pd.DataFrame | None,
                crop: str) -> pd.DataFrame:
    """Daily frame for one crop: price (primary), price_min/max, price2 (second variant), arrivals, rain, tmax."""
    p = prices[prices["crop"] == crop].copy()
    if p.empty:
        return pd.DataFrame()
    p["date"] = pd.to_datetime(p["date"])
    prim = p[p["is_primary"] == 1].set_index("date").sort_index()
    idx = pd.date_range(prim.index.min(), prim.index.max(), freq="D")
    f = pd.DataFrame(index=idx)
    price = prim["avg_kg"].where(prim["carried_over"] == 0)
    f["price_raw"] = price.reindex(idx)
    f["price"] = f["price_raw"].ffill(limit=MAX_FILL_DAYS)
    f["price_min"] = prim["min_kg"].reindex(idx)
    f["price_max"] = prim["max_kg"].reindex(idx)
    f["carried_over"] = prim["carried_over"].reindex(idx).fillna(1)
    others = p[p["is_primary"] == 0]
    if not others.empty:
        second = others.groupby("variant").size().sort_values(ascending=False).index[0]
        s2 = others[others["variant"] == second].set_index("date").sort_index()
        f["price2"] = s2["avg_kg"].where(s2["carried_over"] == 0).reindex(idx).ffill(limit=MAX_FILL_DAYS)
    else:
        f["price2"] = np.nan
    if daily is not None and not daily.empty:
        d = daily[daily["crop"] == crop].copy()
        d["date"] = pd.to_datetime(d["date"])
        f["arrivals"] = d.set_index("date")["arrivals_kg"].reindex(idx)
    else:
        f["arrivals"] = np.nan
    if weather is not None and not weather.empty:
        w = weather.copy()
        w["date"] = pd.to_datetime(w["date"])
        w = w.set_index("date").sort_index()
        f["rain"] = w["rain"].reindex(idx)
        f["tmax"] = w["tmax"].reindex(idx)
    else:
        f["rain"] = np.nan
        f["tmax"] = np.nan
    return f


def primary_variant(prices: pd.DataFrame, crop: str) -> dict:
    """Primary variant name, origin and size for labels."""
    p = prices[(prices["crop"] == crop) & (prices["is_primary"] == 1)]
    if p.empty:
        return {"variant": "", "origin": "", "size": ""}
    r = p.iloc[-1]
    return {"variant": r["variant"], "origin": r["origin"] or "", "size": r["size"] or ""}

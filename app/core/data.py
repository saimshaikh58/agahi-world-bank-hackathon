"""In-memory, per-data-version cache of the lookups the chatbot needs (keeps replies < 100 ms)."""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from app import db
from app.core.aliases import CROP_ORDER
from app.forecast import predict

_lock = threading.Lock()
_store: "DataStore | None" = None


class DataStore:
    """Prices, arrivals and forecasts for the active dataset and latest model run."""

    def __init__(self) -> None:
        self.data_version = db.get_meta("data_version")
        self.run_id = predict.latest_run_id()
        self.is_sample = bool(db.get_meta("is_sample", False))
        with db.connect() as c:
            self.prices = pd.read_sql_query("SELECT * FROM prices", c)
            self.daily = pd.read_sql_query("SELECT date, crop, arrivals_kg FROM daily_crop", c)
        self.today = self.prices["date"].max() if not self.prices.empty else None
        self.forecasts = predict.latest_forecasts()
        present = set(self.prices["crop"].unique()) if not self.prices.empty else set()
        self._crops = [c for c in CROP_ORDER if c in present] + sorted(present - set(CROP_ORDER))
        self._cache: dict = {}

    def crops(self) -> list[str]:
        """Crops with price data, in menu order."""
        return self._crops

    def price_today(self, crop: str) -> dict | None:
        """Latest primary-variant price, previous real price and change."""
        key = ("price", crop)
        if key in self._cache:
            return self._cache[key]
        p = self.prices[(self.prices["crop"] == crop) & (self.prices["is_primary"] == 1)].sort_values("date")
        if p.empty:
            return None
        real = p[p["carried_over"] == 0]
        if real.empty:
            return None
        last = real.iloc[-1]
        prev = real.iloc[-2] if len(real) > 1 else None
        latest_row = p.iloc[-1]
        stale = bool(latest_row["carried_over"]) or last["date"] != self.today
        out = {"crop": crop, "price": float(last["avg_kg"]), "date": last["date"],
               "min": last["min_kg"], "max": last["max_kg"], "origin": last["origin"] or "", "size": last["size"] or "",
               "variant": last["variant"], "prev": float(prev["avg_kg"]) if prev is not None else None,
               "prev_date": prev["date"] if prev is not None else None, "stale": stale}
        r7 = real[pd.to_datetime(real["date"]) <= pd.to_datetime(last["date"]) - pd.Timedelta(days=7)]
        out["ret7"] = float(last["avg_kg"] / r7.iloc[-1]["avg_kg"] - 1) if not r7.empty else None
        self._cache[key] = out
        return out

    def variants(self, crop: str) -> list[dict]:
        """Latest price of each variant of a crop."""
        p = self.prices[(self.prices["crop"] == crop) & (self.prices["carried_over"] == 0)].sort_values("date")
        out = []
        for v, g in p.groupby("variant"):
            r = g.iloc[-1]
            out.append({"variant": v, "origin": r["origin"] or "", "size": r["size"] or "", "price": float(r["avg_kg"]),
                        "date": r["date"], "primary": bool(r["is_primary"])})
        return sorted(out, key=lambda x: -int(x["primary"]))

    def arrivals(self, crop: str) -> dict | None:
        """Latest arrivals (kg) and change vs previous 7-day average."""
        d = self.daily[(self.daily["crop"] == crop)].dropna(subset=["arrivals_kg"]).sort_values("date")
        if d.empty:
            return None
        last = d.iloc[-1]
        prev7 = d.iloc[-8:-1]["arrivals_kg"]
        avg = float(prev7.mean()) if len(prev7) else np.nan
        pct = (float(last["arrivals_kg"]) / avg - 1) * 100 if avg and np.isfinite(avg) and avg > 0 else None
        return {"kg": float(last["arrivals_kg"]), "date": last["date"], "pct_vs_7d": pct}

    def forecast(self, crop: str, horizon: str) -> dict | None:
        """Production forecast row for crop x horizon (None = not trained)."""
        return self.forecasts.get((crop, horizon))


def store() -> DataStore:
    """Current store; rebuilt when the data version or model run changes."""
    global _store
    with _lock:
        dv = db.get_meta("data_version")
        rid = predict.latest_run_id()
        if _store is None or _store.data_version != dv or _store.run_id != rid:
            _store = DataStore()
        return _store


def invalidate() -> None:
    """Force a rebuild on next access."""
    global _store
    with _lock:
        _store = None

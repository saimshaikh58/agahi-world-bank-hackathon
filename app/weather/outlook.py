"""Weather answers for a location: next 7 days (live or climatology), weeks 2-4, months 1-3 (climatology)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app import db
from app.util import now
from app.weather import climatology, live, wmodels

MAX_DATA_LAG_FOR_MODELS = 7


def _loc(key: str) -> dict:
    return db.q1("SELECT * FROM locations WHERE key=?", (key,)) or {"key": key, "lat": None, "lon": None}


def today() -> date:
    """Real calendar date in Kathmandu (weather uses the real date, prices use the data date)."""
    return now().date()


def next7(location: str, offline: bool = False) -> dict:
    """Daily values for the next 7 days. method: live | cache | climatology."""
    loc = _loc(location)
    days, source = live.forecast7(location, loc.get("lat"), loc.get("lon"), offline)
    if days:
        rain = [d["rain"] or 0.0 for d in days]
        tmax = [d["tmax"] for d in days if d["tmax"] is not None]
        wettest = int(np.argmax(rain))
        return {"method": source, "status": "forecast", "days": days, "rain_total": float(sum(rain)),
                "wettest_date": days[wettest]["date"], "wettest_mm": float(rain[wettest]),
                "tmax_lo": float(min(tmax)) if tmax else None, "tmax_hi": float(max(tmax)) if tmax else None,
                "tomorrow_rain": float(rain[1]) if len(rain) > 1 else float(rain[0]),
                "no_coords": loc.get("lat") is None}
    out = []
    t = today()
    for i in range(1, 8):
        d = t + timedelta(days=i)
        c = climatology.day(location, d.timetuple().tm_yday) or {}
        out.append({"date": d.isoformat(), "rain": c.get("rain_mean"), "tmax": c.get("tmax_mean"),
                    "tmin": c.get("tmin_mean"), "p_rain": c.get("p_rain"), "wind": c.get("wind_mean")})
    rain = [d["rain"] or 0.0 for d in out]
    tmax = [d["tmax"] for d in out if d["tmax"] is not None and np.isfinite(d["tmax"])]
    p_rain = [d["p_rain"] for d in out if d["p_rain"] is not None]
    return {"method": "climatology", "status": "climatology", "days": out, "rain_total": float(sum(rain)),
            "rain_chance": float(np.mean(p_rain)) if p_rain else None,
            "tmax_lo": float(min(tmax)) if tmax else None, "tmax_hi": float(max(tmax)) if tmax else None,
            "tomorrow_rain": float(rain[0]), "wettest_date": None, "wettest_mm": None,
            "no_coords": loc.get("lat") is None}


def _series(location: str) -> pd.DataFrame:
    return climatology.load_weather(location).sort_values("date")


def weeks24(location: str) -> dict:
    """Weekly outlook for weeks 2-4. Model only if it beat climatology and the data is fresh."""
    g = _series(location)
    if g.empty:
        return {"method": "none", "weeks": []}
    lag = (today() - g["date"].max().date()).days
    kept = {(r["week"], r["variable"]) for r in db.q(
        "SELECT week, variable FROM weather_backtest WHERE location=? AND kept=1 AND run_id=(SELECT MAX(run_id) FROM weather_backtest)",
        (location,))}
    weeks = []
    t = today()
    for w in wmodels.WEEKS:
        days = pd.date_range(pd.Timestamp(t) + pd.Timedelta(days=7 * (w - 1) + 1), periods=7)
        entry = {"week": w, "start": days[0].strftime("%Y-%m-%d")}
        for var in ("rain_total", "tmax_mean"):
            pred = None
            if (w, var) in kept and lag <= MAX_DATA_LAG_FOR_MODELS:
                v, agg = wmodels._daily_source(g, var)
                pred = wmodels.predict_week(location, var, w, v, agg)
            if pred:
                entry[var] = {"p10": max(0.0, pred[0]) if var == "rain_total" else pred[0], "p50": pred[1],
                              "p90": pred[2], "method": "model"}
            else:
                entry[var] = _clim_week(g, days, var)
        weeks.append(entry)
    method = "model" if any(e[v]["method"] == "model" for e in weeks for v in ("rain_total", "tmax_mean")) else "climatology"
    return {"method": method, "weeks": weeks, "data_lag_days": lag}


def _clim_week(g: pd.DataFrame, days: pd.DatetimeIndex, var: str) -> dict:
    """Empirical distribution of the same calendar week across past years."""
    vals = []
    for y in sorted(g["date"].dt.year.unique()):
        try:
            s = pd.Timestamp(year=int(y), month=days[0].month, day=days[0].day)
        except ValueError:
            continue
        m = (g["date"] >= s) & (g["date"] < s + pd.Timedelta(days=7))
        sub = g[m]
        if len(sub) < 6:
            continue
        vals.append(sub["rain"].sum() if var == "rain_total" else sub["tmax"].mean())
    if not vals:
        return {"p10": None, "p50": None, "p90": None, "method": "climatology"}
    q = np.quantile(vals, [0.1, 0.5, 0.9])
    return {"p10": float(q[0]), "p50": float(q[1]), "p90": float(q[2]), "method": "climatology", "n_years": len(vals)}


def months13(location: str) -> dict:
    """Months 1-3 rain outlook: climatology with tercile probabilities nudged by the last 30 days' anomaly."""
    g = _series(location)
    if g.empty:
        return {"method": "none", "months": []}
    g = g.set_index("date")
    last = g.index.max()
    recent = g["rain"].loc[last - pd.Timedelta(days=29):last].sum()
    past_same = []
    for y in sorted(set(g.index.year) - {last.year}):
        try:
            e = last.replace(year=int(y))
        except ValueError:
            continue
        past_same.append(g["rain"].loc[e - pd.Timedelta(days=29):e].sum())
    norm30 = float(np.median(past_same)) if past_same else recent
    anomaly = float(recent - norm30)
    months = []
    t = pd.Timestamp(today())
    for m in (1, 2, 3):
        start = t + pd.Timedelta(days=30 * (m - 1) + 1)
        totals, cond = [], []
        for y in sorted(set(g.index.year)):
            try:
                s = start.replace(year=int(y))
            except ValueError:
                continue
            win = g["rain"].loc[s:s + pd.Timedelta(days=29)]
            if len(win) < 25:
                continue
            totals.append(win.sum())
            prior = g["rain"].loc[s - pd.Timedelta(days=30):s - pd.Timedelta(days=1)].sum()
            cond.append((win.sum(), prior))
        if len(totals) < 3:
            months.append({"month": m, "p10": None, "p50": None, "p90": None, "probs": None})
            continue
        q = np.quantile(totals, [0.1, 0.5, 0.9])
        t1, t2 = np.quantile(totals, [1 / 3, 2 / 3])
        same = [tot for tot, pr in cond if np.sign(pr - norm30) == np.sign(anomaly)] or totals
        raw = np.array([np.mean([x < t1 for x in same]), np.mean([t1 <= x <= t2 for x in same]),
                        np.mean([x > t2 for x in same])])
        probs = 0.5 * raw + 0.5 / 3
        months.append({"month": m, "start": start.strftime("%Y-%m-%d"), "p10": float(q[0]), "p50": float(q[1]),
                       "p90": float(q[2]), "probs": {"below": float(probs[0]), "near": float(probs[1]),
                                                     "above": float(probs[2])}, "n_years": len(totals)})
    return {"method": "climatology", "months": months, "recent30_mm": float(recent), "normal30_mm": norm30,
            "anomaly30_mm": anomaly, "data_end": last.strftime("%Y-%m-%d")}

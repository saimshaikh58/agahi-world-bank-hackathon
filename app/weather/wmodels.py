"""Weeks 2-4 weather models vs climatology, walk-forward by year blocks with a 28-day embargo."""
from __future__ import annotations

import logging
from typing import Callable

import joblib
import numpy as np
import pandas as pd

from app import db
from app.config import MODELS_DIR, REPORTS_DIR
from app.weather import climatology

log = logging.getLogger("agahi.weather.models")
WEEKS = (2, 3, 4)
VARIABLES = ("rain_total", "rainy_days", "tmax_mean", "tmin_mean")
KEEP_SKILL = 0.03
EMBARGO_DAYS = 28
MIN_TRAIN_YEARS = 3
STEP_DAYS = 7
FEATS = ["anom7", "anom14", "anom30", "doy_sin", "doy_cos", "lastyear"]
WDIR = MODELS_DIR / "weather"


def _daily_source(g: pd.DataFrame, var: str) -> tuple[pd.Series, str]:
    """Daily driver series and aggregation (sum or mean) for a weekly variable."""
    s = g.set_index("date").asfreq("D")
    if var == "rain_total":
        return s["rain"], "sum"
    if var == "rainy_days":
        return (s["rain"] >= climatology.RAIN_DAY_MM).astype(float).where(s["rain"].notna()), "sum"
    return (s["tmax"] if var == "tmax_mean" else s["tmin"]), "mean"


def _clim_daily(v: pd.Series, years_mask: list[int] | None) -> np.ndarray:
    """Daily climatology (366,) from the given years only (earlier years in backtests)."""
    S, C, years = climatology.smoothed_mean_matrix(v)
    rows = [i for i, y in enumerate(years) if years_mask is None or y in years_mask]
    if not rows:
        return np.full(366, np.nan)
    return S[rows].sum(0) / np.maximum(C[rows].sum(0), 1)


def _dataset(v: pd.Series, agg: str, clim: np.ndarray, week: int) -> pd.DataFrame:
    """Feature/target frame for every day; caller subsamples origins."""
    cs = pd.Series(clim[v.index.dayofyear.values - 1], index=v.index)
    a = v - cs
    roll = (lambda s, n: s.rolling(n, min_periods=n).sum()) if agg == "sum" else (lambda s, n: s.rolling(n, min_periods=n).mean())
    df = pd.DataFrame(index=v.index)
    df["anom7"], df["anom14"], df["anom30"] = roll(a, 7), roll(a, 14), roll(a, 30)
    doy = v.index.dayofyear.values
    df["doy_sin"], df["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    shift = -7 * week
    df["target"] = roll(v, 7).shift(shift)
    df["climexp"] = roll(cs, 7).shift(shift)
    df["tanom"] = df["target"] - df["climexp"]
    df["lastyear"] = df["tanom"].shift(365)
    return df


def train_weather_models(run_id: int, progress: Callable[[float, str], None], cancelled: Callable[[], bool],
                         p0: float = 0.0, p1: float = 1.0) -> list[dict]:
    """Backtest and save weekly models for every location; returns backtest rows."""
    wx = climatology.load_weather()
    WDIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    locs = sorted(wx["location"].unique())
    for i, loc in enumerate(locs):
        if cancelled():
            break
        progress(p0 + (p1 - p0) * i / max(len(locs), 1), f"Weather models: {loc}")
        g = wx[wx["location"] == loc].sort_values("date")
        for var in VARIABLES:
            v, agg = _daily_source(g, var)
            for week in WEEKS:
                rows.append(_cell(run_id, loc, var, week, v, agg))
    if rows:
        db.xmany("INSERT INTO weather_backtest VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 [(r["run_id"], r["location"], r["week"], r["variable"], r["mae_model"], r["mae_clim"],
                   r["pinball_model"], r["pinball_clim"], r["skill"], r["n"], r["kept"]) for r in rows])
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(REPORTS_DIR / "backtest_weather.csv", index=False)
    return rows


def _ridge():
    from sklearn.linear_model import Ridge  # training only
    return Ridge(alpha=10.0)


def _pin(a: np.ndarray, q: np.ndarray, tau: float) -> float:
    d = a - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def _cell(run_id: int, loc: str, var: str, week: int, v: pd.Series, agg: str) -> dict:
    years = sorted(v.dropna().index.year.unique().tolist())
    errs_m, errs_c, pins_m, pins_c = [], [], [], []
    for Y in years[MIN_TRAIN_YEARS:]:
        train_years = [y for y in years if y < Y]
        df = _dataset(v, agg, _clim_daily(v, train_years), week).iloc[::STEP_DAYS].dropna()
        cutoff = pd.Timestamp(year=Y, month=1, day=1) - pd.Timedelta(days=EMBARGO_DAYS + 1)
        tr, te = df[df.index <= cutoff], df[df.index.year == Y]
        if len(tr) < 50 or te.empty:
            continue
        m = _ridge().fit(tr[FEATS].values, tr["tanom"].values)
        res = tr["tanom"].values - m.predict(tr[FEATS].values)
        bias = float(np.median(tr["tanom"]))
        pm = m.predict(te[FEATS].values)
        a = te["tanom"].values
        errs_m.append(np.abs(pm - a))
        errs_c.append(np.abs(bias - a))
        qm = np.quantile(res, [0.1, 0.9])
        qc = np.quantile(tr["tanom"].values, [0.1, 0.9])
        pins_m.append(np.mean([_pin(a, pm + qm[0], 0.1), _pin(a, pm, 0.5), _pin(a, pm + qm[1], 0.9)]))
        pins_c.append(np.mean([_pin(a, np.full_like(a, qc[0]), 0.1), _pin(a, np.full_like(a, bias), 0.5),
                               _pin(a, np.full_like(a, qc[1]), 0.9)]))
    if not errs_m:
        return dict(run_id=run_id, location=loc, week=week, variable=var, mae_model=None, mae_clim=None,
                    pinball_model=None, pinball_clim=None, skill=None, n=0, kept=0)
    mae_m, mae_c = float(np.mean(np.concatenate(errs_m))), float(np.mean(np.concatenate(errs_c)))
    skill = 1 - mae_m / mae_c if mae_c > 0 else 0.0
    kept = int(skill >= KEEP_SKILL)
    if kept:
        df = _dataset(v, agg, _clim_daily(v, None), week).iloc[::STEP_DAYS].dropna()
        m = _ridge().fit(df[FEATS].values, df["tanom"].values)
        res = df["tanom"].values - m.predict(df[FEATS].values)
        joblib.dump({"coef": m.coef_.tolist(), "intercept": float(m.intercept_),
                     "q": np.quantile(res, [0.1, 0.9]).tolist(), "feats": FEATS},
                    WDIR / f"{loc}_w{week}_{var}.joblib", compress=3)
    return dict(run_id=run_id, location=loc, week=week, variable=var, mae_model=mae_m, mae_clim=mae_c,
                pinball_model=float(np.mean(pins_m)), pinball_clim=float(np.mean(pins_c)), skill=skill,
                n=int(sum(len(e) for e in errs_m)), kept=kept)


def predict_week(loc: str, var: str, week: int, v: pd.Series, agg: str) -> tuple[float, float, float] | None:
    """Model prediction (p10, p50, p90) of the weekly value from the latest data, if a kept model exists."""
    path = WDIR / f"{loc}_w{week}_{var}.joblib"
    if not path.exists():
        return None
    art = joblib.load(path)
    clim = _clim_daily(v, None)
    feats = _dataset(v, agg, clim, week)[FEATS].dropna()
    if feats.empty:
        return None
    row = feats.iloc[[-1]]
    origin = row.index[-1]
    days = pd.date_range(origin + pd.Timedelta(days=7 * (week - 1) + 1), periods=7)
    vals = clim[days.dayofyear.values - 1]
    exp = float(vals.sum() if agg == "sum" else vals.mean())
    p = float(np.dot(row.values[0], np.array(art["coef"])) + art["intercept"])
    return exp + p + art["q"][0], exp + p, exp + p + art["q"][1]

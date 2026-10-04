"""Per-location day-of-year climatology (smoothed +/- 7 days)."""
from __future__ import annotations

import logging

import joblib
import numpy as np
import pandas as pd

from app import db
from app.config import MODELS_DIR, settings

log = logging.getLogger("agahi.weather")
WINDOW = 7
RAIN_DAY_MM = 1.0
HEAVY_MM = 20.0
CLIM_PATH = MODELS_DIR / "weather" / "climatology.joblib"
_CACHE: dict = {}


def load_weather(location: str | None = None) -> pd.DataFrame:
    """Weather rows from DB (one location or all)."""
    with db.connect() as c:
        if location:
            df = pd.read_sql_query("SELECT * FROM weather WHERE location=? ORDER BY date", c, params=(location,))
        else:
            df = pd.read_sql_query("SELECT * FROM weather ORDER BY date", c)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _circ_dist(a: np.ndarray, b: int) -> np.ndarray:
    d = np.abs(a - b)
    return np.minimum(d, 366 - d)


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Climatology table indexed by (location, doy)."""
    out = []
    for loc, g in df.groupby("location"):
        doy = g["date"].dt.dayofyear.values
        rain, tmax, tmin, wind = (g[c].values for c in ("rain", "tmax", "tmin", "wind"))
        for d in range(1, 367):
            m = _circ_dist(doy, d) <= WINDOW
            r = rain[m][np.isfinite(rain[m])]
            tx = tmax[m][np.isfinite(tmax[m])]
            tn = tmin[m][np.isfinite(tmin[m])]
            if len(r) == 0:
                continue
            rq = np.quantile(r, [0.1, 0.5, 0.9])
            txq = np.quantile(tx, [0.1, 0.5, 0.9]) if len(tx) else [np.nan] * 3
            tnq = np.quantile(tn, [0.1, 0.5, 0.9]) if len(tn) else [np.nan] * 3
            out.append(dict(location=loc, doy=d, rain_mean=float(r.mean()), rain_p10=rq[0], rain_p50=rq[1],
                            rain_p90=rq[2], p_rain=float((r >= RAIN_DAY_MM).mean()), p_heavy=float((r >= HEAVY_MM).mean()),
                            tmax_mean=float(np.mean(tx)) if len(tx) else np.nan, tmax_p10=txq[0], tmax_p50=txq[1], tmax_p90=txq[2],
                            tmin_mean=float(np.mean(tn)) if len(tn) else np.nan, tmin_p10=tnq[0], tmin_p50=tnq[1], tmin_p90=tnq[2],
                            wind_mean=float(np.nanmean(wind[m])) if np.isfinite(wind[m]).any() else np.nan))
    return pd.DataFrame(out).set_index(["location", "doy"]) if out else pd.DataFrame()


def _key() -> str:
    """Identifies the dataset a climatology was built from."""
    return f"{settings.db_path}:{db.get_meta('data_version')}"


def build_and_save() -> pd.DataFrame:
    """Compute from DB and persist (tagged with the dataset it came from)."""
    clim = compute(load_weather())
    CLIM_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"key": _key(), "clim": clim}, CLIM_PATH, compress=3)
    _CACHE.clear()
    _CACHE.update(key=_key(), clim=clim)
    return clim


def get() -> pd.DataFrame:
    """Cached climatology; rebuilt if missing or built from another dataset."""
    key = _key()
    if _CACHE.get("key") == key and "clim" in _CACHE:
        return _CACHE["clim"]
    art = None
    if CLIM_PATH.exists():
        try:
            art = joblib.load(CLIM_PATH)
        except Exception:  # corrupt file -> rebuild
            art = None
    if isinstance(art, dict) and art.get("key") == key and not art["clim"].empty:
        _CACHE.update(key=key, clim=art["clim"])
        return art["clim"]
    return build_and_save()


def day(location: str, doy: int) -> dict | None:
    """Climatology row for one location and day of year."""
    clim = get()
    try:
        return clim.loc[(location, int(doy))].to_dict()
    except KeyError:
        return None


def smoothed_mean_matrix(series: pd.Series) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Per-year windowed sums and counts (years x 366) so climatology from earlier years is cheap."""
    s = series.dropna()
    years = sorted(s.index.year.unique().tolist())
    A = np.full((len(years), 366), np.nan)
    yi = {y: i for i, y in enumerate(years)}
    for d, v in s.items():
        A[yi[d.year], d.dayofyear - 1] = v
    vals = np.nan_to_num(A)
    cnt = np.isfinite(A).astype(float)
    S = np.zeros_like(vals)
    C = np.zeros_like(cnt)
    for k in range(-WINDOW, WINDOW + 1):
        S += np.roll(vals, k, axis=1)
        C += np.roll(cnt, k, axis=1)
    return S, C, years

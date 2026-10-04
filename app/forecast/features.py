"""Features at origin t use only data at or before t (no leakage). Targets look forward."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.forecast.prep import HORIZON_DAYS, MONTH_HORIZONS

WEATHER_FILL_DAYS = 14
FEATURES = ["lp", "ret1", "ret3", "ret7", "ret14", "ret28", "z90", "mr_gap", "vol14", "arr_z30", "arr_ratio",
            "rain3", "rain7", "rain14", "rain28", "rainy7", "rainy28", "tmax7", "tmax28",
            "doy_sin", "doy_cos", "month", "gap2"]
WEATHER_FEATURES = ["rain3", "rain7", "rain14", "rain28", "rainy7", "rainy28", "tmax7", "tmax28"]


def build_features(f: pd.DataFrame) -> pd.DataFrame:
    """Build the feature matrix from a crop frame (see prep.build_frame)."""
    X = pd.DataFrame(index=f.index)
    lp = np.log(f["price"])
    X["lp"] = lp
    for k in (1, 3, 7, 14, 28):
        X[f"ret{k}"] = lp - lp.shift(k)
    m90 = f["price"].rolling(90, min_periods=30).mean()
    s90 = f["price"].rolling(90, min_periods=30).std()
    X["z90"] = (f["price"] - m90) / s90.replace(0, np.nan)
    X["mr_gap"] = np.log(m90) - lp
    X["vol14"] = lp.diff().rolling(14, min_periods=7).std()
    la = np.log1p(f["arrivals"])
    X["arr_z30"] = (la - la.rolling(30, min_periods=10).mean()) / la.rolling(30, min_periods=10).std().replace(0, np.nan)
    X["arr_ratio"] = f["arrivals"].rolling(7, min_periods=4).mean() / f["arrivals"].rolling(28, min_periods=14).mean()
    rain = f["rain"]
    for k in (3, 7, 14, 28):
        X[f"rain{k}"] = rain.rolling(k, min_periods=k).sum()
    X["rainy7"] = (rain >= 1).astype(float).where(rain.notna()).rolling(7, min_periods=7).sum()
    X["rainy28"] = (rain >= 1).astype(float).where(rain.notna()).rolling(28, min_periods=28).sum()
    X["tmax7"] = f["tmax"].rolling(7, min_periods=7).mean()
    X["tmax28"] = f["tmax"].rolling(28, min_periods=28).mean()
    X[WEATHER_FEATURES] = X[WEATHER_FEATURES].ffill(limit=WEATHER_FILL_DAYS)
    doy = f.index.dayofyear.values
    X["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    X["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    X["month"] = f.index.month.values.astype(float)
    X["gap2"] = lp - np.log(f["price2"]) if "price2" in f else np.nan
    X = X[FEATURES].replace([np.inf, -np.inf], np.nan)
    empty = [c for c in FEATURES if X[c].notna().sum() == 0]
    X[empty] = 0.0  # a feature with no data at all (e.g. no second variant) becomes a constant
    return X


def build_target(f: pd.DataFrame, h: str) -> pd.Series:
    """y = log(P[t+h]/P[t]) for day horizons; mean of P[t+h-3..t+h+3] for month horizons."""
    n = HORIZON_DAYS[h]
    lp = np.log(f["price"])
    if h in MONTH_HORIZONS:
        future = f["price"].rolling(7, min_periods=4).mean().shift(-(n + 3))
        return np.log(future) - lp
    return np.log(f["price"].shift(-n)) - lp

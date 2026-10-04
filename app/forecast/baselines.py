"""Baseline forecasters: persistence, seasonal-naive (earlier years only), mean reversion."""
from __future__ import annotations

import numpy as np
import pandas as pd

SEASON_WINDOW = 7


def _doy_dist(a: np.ndarray, b: int) -> np.ndarray:
    d = np.abs(a - b)
    return np.minimum(d, 366 - d)


def seasonal_naive(train_y: np.ndarray, train_dates: pd.DatetimeIndex, test_dates: pd.DatetimeIndex) -> np.ndarray:
    """Median log-ratio at the same day of year +/- 7 days, using only earlier years than each test origin."""
    tdoy = train_dates.dayofyear.values
    tyear = train_dates.year.values
    out = np.zeros(len(test_dates))
    for i, d in enumerate(test_dates):
        m = (_doy_dist(tdoy, d.dayofyear) <= SEASON_WINDOW) & (tyear < d.year)
        vals = train_y[m]
        out[i] = float(np.median(vals)) if len(vals) >= 5 else 0.0
    return out


def seasonal_range(all_y: np.ndarray, all_dates: pd.DatetimeIndex, origin: pd.Timestamp,
                   qs: tuple = (0.1, 0.5, 0.9)) -> tuple | None:
    """Quantiles (P10/P50/P90 by default) of historical log-ratios around this day of year (pattern only)."""
    m = _doy_dist(all_dates.dayofyear.values, origin.dayofyear) <= SEASON_WINDOW
    vals = all_y[m]
    if len(vals) < 15:
        vals = all_y
    if len(vals) < 15:
        return None
    return tuple(float(x) for x in np.quantile(vals, list(qs)))


class MeanReversion:
    """y = b * mr_gap, b fit by least squares on training rows (no intercept)."""

    def __init__(self) -> None:
        self.b = 0.0

    def fit(self, gap: np.ndarray, y: np.ndarray) -> "MeanReversion":
        m = np.isfinite(gap) & np.isfinite(y)
        den = float(np.sum(gap[m] ** 2))
        self.b = float(np.sum(gap[m] * y[m]) / den) if den > 0 else 0.0
        self.b = max(-2.0, min(2.0, self.b))
        return self

    def predict(self, gap: np.ndarray) -> np.ndarray:
        return np.nan_to_num(self.b * gap)

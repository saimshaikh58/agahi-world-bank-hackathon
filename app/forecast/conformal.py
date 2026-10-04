"""Split-conformal intervals from out-of-fold walk-forward residuals."""
from __future__ import annotations

import numpy as np

LO_Q, HI_Q = 0.1, 0.9
MIN_RESIDUALS = 30


def interval_offsets(residuals: np.ndarray) -> tuple[float, float] | None:
    """Return (lo, hi) offsets so that pred+lo..pred+hi covers ~80%."""
    r = residuals[np.isfinite(residuals)]
    if len(r) < MIN_RESIDUALS:
        return None
    n = len(r)
    # finite-sample adjusted quantile levels
    lo = np.quantile(r, max(0.0, LO_Q - 0.5 / n))
    hi = np.quantile(r, min(1.0, HI_Q + 0.5 / n))
    return float(lo), float(hi)


def sequential_intervals(pred: np.ndarray, actual: np.ndarray, fold: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For each fold k, calibrate on residuals of folds < k only. Rows without enough history get NaN."""
    lo = np.full(len(pred), np.nan)
    hi = np.full(len(pred), np.nan)
    resid = actual - pred
    for k in np.unique(fold):
        off = interval_offsets(resid[fold < k])
        if off is None:
            continue
        m = fold == k
        lo[m] = pred[m] + off[0]
        hi[m] = pred[m] + off[1]
    return lo, hi


def pinball(actual: np.ndarray, q: np.ndarray, tau: float) -> float:
    """Mean pinball loss."""
    d = actual - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))

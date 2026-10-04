"""Expanding-window walk-forward backtest with embargo, metrics and the honest status gate."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from app.forecast import conformal
from app.forecast.baselines import MeanReversion, seasonal_naive
from app.forecast.models import make_hgb, make_ridge

FIRST_TRAIN_DAYS = 365
BLOCK_DAYS = {"fast": 60, "full": 30}
MIN_TRAIN_ROWS = 200
DIR_THRESHOLD = np.log(1.02)
BASELINES = ("persistence", "seasonal_naive", "mean_reversion")
LEARNED = ("ridge", "hgb", "blend")
BLEND_LAMBDAS = (0.0, 0.25, 0.5, 0.75, 1.0)
RELIABLE = dict(skill=0.05, dir_acc=0.58, cov_lo=0.70, cov_hi=0.90, n_test=60)
MIN_TEST_ROWS = 20


def make_folds(dates: pd.DatetimeIndex, gap_days: int, block: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding window folds. Train rows end gap_days+1 before the test block starts (embargo)."""
    folds = []
    if len(dates) == 0:
        return folds
    start = dates.min() + pd.Timedelta(days=FIRST_TRAIN_DAYS)
    end = dates.max()
    t = start
    while t <= end:
        t_end = t + pd.Timedelta(days=block)
        train = np.where(dates <= t - pd.Timedelta(days=gap_days + 1))[0]
        test = np.where((dates >= t) & (dates < t_end))[0]
        if len(train) >= MIN_TRAIN_ROWS and len(test) > 0:
            folds.append((train, test))
        t = t_end
    return folds


def walk_forward(X: pd.DataFrame, y: pd.Series, gap_days: int, mode: str = "fast",
                 cancelled: Callable[[], bool] | None = None) -> dict:
    """Run all candidate models through the folds. Returns OOF predictions per model."""
    dates = X.index
    Xv = X.values
    yv = y.values
    folds = make_folds(dates, gap_days, BLOCK_DAYS.get(mode, 60))
    n = len(yv)
    preds = {m: np.full(n, np.nan) for m in BASELINES + LEARNED}
    fold_id = np.full(n, -1)
    gap_col = list(X.columns).index("mr_gap")
    for k, (tr, te) in enumerate(folds):
        if cancelled and cancelled():
            break
        fold_id[te] = k
        preds["persistence"][te] = 0.0
        preds["seasonal_naive"][te] = seasonal_naive(yv[tr], dates[tr], dates[te])
        preds["mean_reversion"][te] = MeanReversion().fit(Xv[tr, gap_col], yv[tr]).predict(Xv[te, gap_col])
        preds["ridge"][te] = make_ridge().fit(Xv[tr], yv[tr]).predict(Xv[te])
        preds["hgb"][te] = make_hgb(mode).fit(Xv[tr], yv[tr]).predict(Xv[te])
    tested = fold_id >= 0
    best_base = _best(preds, yv, tested, BASELINES)
    preds["blend"] = _blend(preds[best_base], preds["hgb"], yv, fold_id)
    return {"preds": preds, "fold": fold_id, "tested": tested, "best_baseline": best_base, "n_folds": len(folds)}


def _mae(p: np.ndarray, y: np.ndarray, m: np.ndarray) -> float:
    mm = m & np.isfinite(p) & np.isfinite(y)
    return float(np.mean(np.abs(p[mm] - y[mm]))) if mm.any() else float("inf")


def _best(preds: dict, y: np.ndarray, m: np.ndarray, names) -> str:
    return min(names, key=lambda k: _mae(preds[k], y, m))


def _blend(base: np.ndarray, model: np.ndarray, y: np.ndarray, fold: np.ndarray) -> np.ndarray:
    """best_baseline + lambda*(model-baseline); lambda chosen on earlier folds only."""
    out = np.full(len(y), np.nan)
    for k in np.unique(fold[fold >= 0]):
        prior = (fold >= 0) & (fold < k)
        lam = 0.5
        if prior.sum() >= 30:
            lam = min(BLEND_LAMBDAS, key=lambda L: _mae(base + L * (model - base), y, prior))
        m = fold == k
        out[m] = base[m] + lam * (model[m] - base[m])
    return out


def best_lambda(base: np.ndarray, model: np.ndarray, y: np.ndarray, m: np.ndarray) -> float:
    """Lambda on all OOF rows (for the final production blend)."""
    return min(BLEND_LAMBDAS, key=lambda L: _mae(base + L * (model - base), y, m))


def metrics(pred: np.ndarray, y: np.ndarray, fold: np.ndarray, price0: np.ndarray, base_mae: float) -> dict:
    """All per-cell metrics for one model."""
    m = (fold >= 0) & np.isfinite(pred) & np.isfinite(y)
    if m.sum() == 0:
        return {"n_test": 0}
    p, a, f, p0 = pred[m], y[m], fold[m], price0[m]
    mae_log = float(np.mean(np.abs(p - a)))
    rs_pred, rs_act = p0 * np.exp(p), p0 * np.exp(a)
    mae_rs = float(np.mean(np.abs(rs_pred - rs_act)))
    mape = float(np.mean(np.abs(rs_pred - rs_act) / rs_act))
    big = np.abs(a) >= DIR_THRESHOLD
    dir_acc = float(np.mean(np.sign(p[big]) == np.sign(a[big]))) if big.any() else float("nan")
    lo, hi = conformal.sequential_intervals(p, a, f)
    cm = np.isfinite(lo)
    coverage = float(np.mean((a[cm] >= lo[cm]) & (a[cm] <= hi[cm]))) if cm.any() else float("nan")
    width = float(np.mean(np.exp(hi[cm]) - np.exp(lo[cm]))) if cm.any() else float("nan")
    pin = float(np.mean([conformal.pinball(a[cm], lo[cm], 0.1), conformal.pinball(a[cm], p[cm], 0.5),
                         conformal.pinball(a[cm], hi[cm], 0.9)])) if cm.any() else float("nan")
    skill = 1 - mae_log / base_mae if base_mae > 0 else 0.0
    return dict(mae_log=mae_log, mae_rs=mae_rs, mape=mape, dir_acc=dir_acc, skill=skill, pinball=pin,
                coverage=coverage, width=width, n_test=int(m.sum()))


def decide_status(model: str, met: dict, horizon: str) -> str:
    """Status gate: reliable / indicative / pattern only / unavailable."""
    if met.get("n_test", 0) < MIN_TEST_ROWS:
        return "unavailable"
    if model in BASELINES:
        return "pattern only"
    cov = met.get("coverage", float("nan"))
    cov_ok = np.isfinite(cov) and RELIABLE["cov_lo"] <= cov <= RELIABLE["cov_hi"]
    dacc = met.get("dir_acc", float("nan"))
    if (horizon.startswith("d") and met["skill"] >= RELIABLE["skill"] and np.isfinite(dacc)
            and dacc >= RELIABLE["dir_acc"] and cov_ok and met["n_test"] >= RELIABLE["n_test"]):
        return "reliable"
    if met["skill"] >= 0 and cov_ok:
        return "indicative"
    return "pattern only"

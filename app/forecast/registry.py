"""Train, evaluate, select and save price models for every crop x horizon. Writes DB rows and artifacts."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd

from app import db
from app.config import MODELS_DIR, REPORTS_DIR
from app.forecast import backtest, conformal
from app.forecast.baselines import MeanReversion, seasonal_naive, seasonal_range
from app.forecast.features import FEATURES, build_features, build_target
from app.forecast.models import make_hgb, make_ridge
from app.forecast.prep import HORIZONS, HORIZON_DAYS, MONTH_HORIZONS, build_frame, load_tables, target_gap
from app.util import now_iso

log = logging.getLogger("agahi.forecast")
PRICE_DIR = MODELS_DIR / "price"
MIN_ROWS = 365 + 60
IMPORTANCE_ROWS = 365


def train_prices(run_id: int, mode: str, progress: Callable[[float, str], None],
                 cancelled: Callable[[], bool], p0: float = 0.0, p1: float = 1.0) -> list[dict]:
    """Backtest + final fit for all crops x horizons. Returns summary rows."""
    prices, daily, weather = load_tables()
    crops = sorted(prices["crop"].unique().tolist())
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []
    all_rows: list[dict] = []
    for i, crop in enumerate(crops):
        if cancelled():
            break
        progress(p0 + (p1 - p0) * i / max(len(crops), 1), f"Price models: {crop}")
        frame = build_frame(prices, daily, weather, crop)
        X = build_features(frame) if not frame.empty else pd.DataFrame()
        for h in HORIZONS:
            if cancelled():
                break
            res = _train_cell(run_id, crop, h, frame, X, mode)
            summary.append(res["summary"])
            all_rows.extend(res["rows"])
    if all_rows:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(all_rows).to_csv(REPORTS_DIR / "backtest_price.csv", index=False)
    return summary


def _train_cell(run_id: int, crop: str, h: str, frame: pd.DataFrame, X: pd.DataFrame, mode: str) -> dict:
    origin = frame.index.max() if not frame.empty else None
    price0 = float(frame["price"].ffill().iloc[-1]) if not frame.empty else float("nan")
    if frame.empty:
        return _unavailable(run_id, crop, h, origin, price0)
    y = build_target(frame, h)
    valid = y.notna() & X["lp"].notna()
    Xv, yv = X[valid], y[valid]
    if len(yv) < MIN_ROWS:
        return _unavailable(run_id, crop, h, origin, price0)
    wf = backtest.walk_forward(Xv, yv, target_gap(h), mode)
    p0 = np.exp(Xv["lp"].values)
    base_name = wf["best_baseline"]
    base_mae = backtest._mae(wf["preds"][base_name], yv.values, wf["tested"])
    rows, mets = [], {}
    for name, pred in wf["preds"].items():
        met = backtest.metrics(pred, yv.values, wf["fold"], p0, base_mae)
        mets[name] = met
    eligible = [m for m in mets if mets[m].get("n_test", 0) > 0]
    if not eligible:
        return _unavailable(run_id, crop, h, origin, price0)
    chosen = min(eligible, key=lambda m: mets[m]["mae_log"])
    status = backtest.decide_status(chosen, mets[chosen], h)
    if h in MONTH_HORIZONS and status == "reliable":
        status = "indicative"
    for name, met in mets.items():
        st = backtest.decide_status(name, met, h)
        if h in MONTH_HORIZONS and st == "reliable":
            st = "indicative"
        row = dict(run_id=run_id, crop=crop, horizon=h, model=name, chosen=int(name == chosen), status=st, **{
            k: _clean(met.get(k)) for k in ("mae_log", "mae_rs", "mape", "dir_acc", "skill", "pinball",
                                            "coverage", "width", "n_test")})
        rows.append(row)
    db.xmany("INSERT INTO backtest_results(run_id,crop,horizon,model,mae_log,mae_rs,mape,dir_acc,skill,pinball,"
             "coverage,width,n_test,chosen,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             [(r["run_id"], r["crop"], r["horizon"], r["model"], r["mae_log"], r["mae_rs"], r["mape"], r["dir_acc"],
               r["skill"], r["pinball"], r["coverage"], r["width"], r["n_test"], r["chosen"], r["status"])
              for r in rows])
    _save_test_preds(run_id, crop, h, Xv.index, p0, yv.values, wf, chosen)
    final = _final_fit(chosen, base_name, Xv, yv, X, wf, mode, h)
    offsets = conformal.interval_offsets(yv.values[wf["tested"]] - wf["preds"][chosen][wf["tested"]])
    t0 = time.perf_counter()
    for _ in range(20):
        point = final["predict"](X.iloc[[-1]])
    infer_ms = (time.perf_counter() - t0) / 20 * 1000
    model_name = chosen
    if status == "pattern only":
        rng = seasonal_range(yv.values, Xv.index, origin)
        lo, mid, hi = rng if rng else (np.nan, np.nan, np.nan)
        model_name = "seasonal pattern"
    elif offsets is None:
        status, lo, mid, hi = "unavailable", np.nan, np.nan, np.nan
    else:
        mid = float(point)
        lo, hi = mid + offsets[0], mid + offsets[1]
    p10, p50, p90 = (price0 * np.exp(v) if np.isfinite(v) else None for v in (lo, mid, hi))
    path = PRICE_DIR / f"{crop}_{h}.joblib"
    joblib.dump({"model": final["object"], "features": FEATURES, "chosen": chosen, "offsets": offsets,
                 "lambda": final.get("lambda")}, path, compress=3)
    importance = _importance(final, Xv, yv, h, mode)
    meta = dict(crop=crop, horizon=h, chosen=chosen, status=status, trained_at=now_iso(),
                data_version=db.get_meta("data_version"), features=FEATURES, metrics=mets[chosen],
                best_baseline=base_name, file_bytes=path.stat().st_size, inference_ms=round(infer_ms, 3),
                importance=importance, n_rows=int(len(yv)))
    path.with_suffix(".json").write_text(json.dumps(meta, default=_clean, indent=1), encoding="utf-8")
    pct = (p50 / price0 - 1) * 100 if p50 and price0 else None
    db.x("INSERT INTO forecasts(run_id,origin_date,crop,horizon,p10,p50,p90,price0,pct_change_p50,status,model_name,skill) "
         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
         (run_id, origin.strftime("%Y-%m-%d"), crop, h, p10, p50, p90, price0, pct, status, model_name,
          _clean(mets[chosen].get("skill"))))
    _ledger(origin, crop, h, p10, p50, p90, price0, status)
    summ = dict(crop=crop, horizon=h, chosen=chosen, status=status, skill=_clean(mets[chosen].get("skill")),
                coverage=_clean(mets[chosen].get("coverage")), n_test=mets[chosen].get("n_test", 0),
                file_bytes=meta["file_bytes"], inference_ms=meta["inference_ms"])
    return {"summary": summ, "rows": rows}


def _final_fit(chosen: str, base_name: str, Xv: pd.DataFrame, yv: pd.Series, X: pd.DataFrame,
               wf: dict, mode: str, h: str) -> dict:
    """Fit the chosen model on all rows; return predict(X_row) and the object to persist."""
    gap_col = "mr_gap"
    known_y, known_d = yv.values, Xv.index

    def base_predict(name: str, row: pd.DataFrame) -> float:
        if name == "persistence":
            return 0.0
        if name == "seasonal_naive":
            return float(seasonal_naive(known_y, known_d, row.index)[0])
        mr = MeanReversion().fit(Xv[gap_col].values, known_y)
        return float(mr.predict(row[gap_col].values)[0])

    if chosen in backtest.BASELINES:
        obj = {"type": chosen}
        if chosen == "mean_reversion":
            obj["b"] = MeanReversion().fit(Xv[gap_col].values, known_y).b
        return {"object": obj, "predict": lambda row: base_predict(chosen, row)}
    if chosen == "ridge":
        m = make_ridge().fit(Xv.values, known_y)
        return {"object": m, "est": m, "predict": lambda row: float(m.predict(row.values)[0])}
    hgb = make_hgb(mode).fit(Xv.values, known_y)
    if chosen == "hgb":
        return {"object": hgb, "est": hgb, "predict": lambda row: float(hgb.predict(row.values)[0])}
    lam = backtest.best_lambda(wf["preds"][base_name], wf["preds"]["hgb"], known_y, wf["tested"])

    def blend(row: pd.DataFrame) -> float:
        b = base_predict(base_name, row)
        return b + lam * (float(hgb.predict(row.values)[0]) - b)
    return {"object": {"type": "blend", "base": base_name, "hgb": hgb}, "est": hgb, "predict": blend, "lambda": lam}


def _importance(final: dict, Xv: pd.DataFrame, yv: pd.Series, h: str, mode: str) -> list[dict]:
    """Permutation importance of the learned model on recent rows (d7/d14 in fast mode)."""
    est = final.get("est")
    if est is None or (mode == "fast" and h not in ("d7", "d14")):
        return []
    Xr, yr = Xv.values[-IMPORTANCE_ROWS:], yv.values[-IMPORTANCE_ROWS:]
    from sklearn.inspection import permutation_importance
    try:
        r = permutation_importance(est, Xr, yr, n_repeats=3, random_state=42, scoring="neg_mean_absolute_error")
    except Exception as e:  # importance is a nice-to-have; never fail training for it
        log.warning("permutation importance skipped: %s", e)
        return []
    items = sorted(zip(FEATURES, r.importances_mean), key=lambda t: -t[1])[:10]
    return [{"feature": f, "importance": float(v)} for f, v in items]


def _save_test_preds(run_id, crop, h, dates, p0, y, wf, chosen) -> None:
    pred = wf["preds"][chosen]
    lo, hi = conformal.sequential_intervals(pred, y, wf["fold"])
    m = wf["tested"] & np.isfinite(pred)
    db.xmany("INSERT INTO backtest_preds VALUES(?,?,?,?,?,?,?,?,?)",
             [(run_id, crop, h, d.strftime("%Y-%m-%d"), float(p), float(a), float(pr), _clean(l), _clean(u))
              for d, p, a, pr, l, u in zip(dates[m], p0[m], y[m], pred[m], lo[m], hi[m])])


def _ledger(origin, crop, h, p10, p50, p90, price0, status) -> None:
    if origin is None or p50 is None:
        return
    target = (origin + pd.Timedelta(days=HORIZON_DAYS[h])).strftime("%Y-%m-%d")
    db.x("INSERT OR IGNORE INTO forecast_ledger(logged_at,origin_date,crop,horizon,target_date,p10,p50,p90,price0,status) "
         "VALUES(?,?,?,?,?,?,?,?,?,?)", (now_iso(), origin.strftime("%Y-%m-%d"), crop, h, target, p10, p50, p90, price0, status))


def fill_ledger() -> int:
    """Fill realised prices for ledger rows whose target date is now in the data."""
    rows = db.q("SELECT l.id, l.crop, l.target_date FROM forecast_ledger l WHERE l.realised IS NULL")
    n = 0
    for r in rows:
        p = db.q1("SELECT avg_kg FROM prices WHERE crop=? AND date=? AND is_primary=1 AND carried_over=0",
                  (r["crop"], r["target_date"]))
        if p:
            db.x("UPDATE forecast_ledger SET realised=? WHERE id=?", (p["avg_kg"], r["id"]))
            n += 1
    return n


def _unavailable(run_id, crop, h, origin, price0) -> dict:
    od = origin.strftime("%Y-%m-%d") if origin is not None else None
    db.x("INSERT INTO forecasts(run_id,origin_date,crop,horizon,p10,p50,p90,price0,pct_change_p50,status,model_name,skill) "
         "VALUES(?,?,?,?,NULL,NULL,NULL,?,NULL,'unavailable','none',NULL)", (run_id, od, crop, h, _clean(price0)))
    return {"summary": dict(crop=crop, horizon=h, chosen="none", status="unavailable", skill=None, coverage=None,
                            n_test=0, file_bytes=0, inference_ms=0), "rows": []}


def _clean(v):
    """JSON/DB-safe float."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def footprint() -> dict:
    """Artifact sizes and inference latency (see app.forecast.predict.footprint)."""
    from app.forecast.predict import footprint as fp
    return fp()

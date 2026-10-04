"""Train-all orchestration: climatology, price models, weather models, intent classifier, linkage, reports."""
from __future__ import annotations

import json
import logging
from typing import Callable

import numpy as np
import pandas as pd

from app import db, reporting
from app.config import REPORTS_DIR
from app.core import data, intent_model, nlu
from app.forecast import registry
from app.forecast.prep import build_frame, load_tables
from app.jobs import JobCancelled
from app.util import now_iso
from app.weather import climatology, outlook, wmodels

log = logging.getLogger("agahi.training")
MAX_LAG = 14


def run_training(progress: Callable[[float, str], None], cancelled: Callable[[], bool], mode: str = "fast") -> int:
    """Full pipeline. Returns model run id."""
    if not db.q1("SELECT 1 AS ok FROM prices LIMIT 1"):
        raise RuntimeError("No dataset loaded. Upload a data ZIP first.")
    run_id = db.x("INSERT INTO model_runs(started_at,mode,data_version) VALUES(?,?,?)",
                  (now_iso(), mode, db.get_meta("data_version")))
    progress(0.02, f"Run {run_id} started ({mode} mode). Data prep and climatology")
    climatology.build_and_save()
    _check(cancelled)
    summary = registry.train_prices(run_id, mode, progress, cancelled, 0.05, 0.70)
    _check(cancelled)
    progress(0.70, "Weather models (weeks 2-4 vs climatology)")
    wrows = wmodels.train_weather_models(run_id, progress, cancelled, 0.70, 0.85)
    _check(cancelled)
    progress(0.86, "Intent classifier")
    ev = intent_model.train(nlu.normalise, run_id)
    db.x("INSERT INTO intent_eval VALUES(?,?,?,?,?,?)", (run_id, ev["accuracy"], json.dumps(ev["by_lang"]),
                                                         json.dumps(ev["confusion"]), json.dumps(ev["labels"]), ev["n_test"]))
    casual = evaluate_casual()
    ev.update(casual)
    (REPORTS_DIR / "intent_eval.json").write_text(json.dumps(ev, indent=1), encoding="utf-8")
    progress(0.90, f"Intent held-out accuracy {ev['accuracy']:.1%} ({ev['chosen']}); "
                   f"casual set {casual['casual_pipeline_accuracy']:.1%} of {casual['casual_n']}")
    progress(0.91, "Weather-market linkage (lagged correlation)")
    corr = weather_market_corr()
    (REPORTS_DIR / "weather_market_corr.json").write_text(json.dumps(corr), encoding="utf-8")
    progress(0.94, "Weather outlooks per location")
    _save_outlooks()
    filled = registry.fill_ledger()
    statuses = pd.Series([s["status"] for s in summary]).value_counts().to_dict() if summary else {}
    summ = {"cells": len(summary), "status_counts": statuses, "weather_kept": int(sum(r["kept"] for r in wrows)),
            "weather_cells": len(wrows), "intent_accuracy": ev["accuracy"], "intent_model": ev["chosen"],
            "casual_accuracy": ev.get("casual_pipeline_accuracy"), "casual_n": ev.get("casual_n"), "ledger_filled": filled,
            "footprint": registry.footprint(), "intent_bytes": ev["file_bytes"]}
    db.x("UPDATE model_runs SET finished_at=?, summary_json=? WHERE id=?", (now_iso(), json.dumps(summ), run_id))
    data.invalidate()
    progress(0.97, "Reports: model card, README results")
    reporting.write_all(run_id)
    progress(1.0, f"Done. Status counts: {statuses}")
    return run_id


def evaluate_casual() -> dict:
    """Run the whole NLU (rules + spell correction + classifier) on the hand-written casual set."""
    rows = intent_model.load_examples(intent_model.CASUAL_FILE)
    nlu._SPELL.clear()
    misses, ok, by_lang = [], 0, {}
    for r in rows:
        p = nlu.parse(r["text"])
        good = p.intent == r["intent"] and (not r.get("crop") or p.slots.get("crop") == r["crop"]) and \
            (not r.get("horizon") or p.slots.get("horizon") == r["horizon"])
        ok += good
        b = by_lang.setdefault(r["lang"], [0, 0])
        b[0] += good
        b[1] += 1
        if not good:
            misses.append({"text": r["text"], "expected": r["intent"], "got": p.intent,
                           "crop": p.slots.get("crop"), "confidence": p.confidence})
    return {"casual_pipeline_accuracy": ok / len(rows) if rows else None, "casual_n": len(rows),
            "casual_by_lang": {k: v[0] / v[1] for k, v in by_lang.items()}, "casual_misses": misses}


def _check(cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise JobCancelled()


def weather_market_corr() -> dict:
    """Lagged correlation of area rain/tmax with 7-day price and arrivals changes, per crop."""
    prices, daily, weather = load_tables()
    out = {"lags": list(range(MAX_LAG + 1)), "crops": {}, "note": "correlation, not causation"}
    for crop in sorted(prices["crop"].unique()):
        f = build_frame(prices, daily, weather, crop)
        if f.empty:
            continue
        rain7 = f["rain"].rolling(7, min_periods=7).sum()
        tmax7 = f["tmax"].rolling(7, min_periods=7).mean()
        dp = np.log(f["price"]) - np.log(f["price"].shift(7))
        da = np.log1p(f["arrivals"]) - np.log1p(f["arrivals"].shift(7))
        rows = {}
        for name, x, y in (("rain_price", rain7, dp), ("rain_arrivals", rain7, da), ("tmax_price", tmax7, dp)):
            vals, ns = [], []
            for lag in out["lags"]:
                pair = pd.concat([x.shift(lag), y], axis=1).dropna()
                ns.append(int(len(pair)))
                vals.append(float(pair.corr().iloc[0, 1]) if len(pair) > 30 else None)
            rows[name] = {"r": vals, "n": ns}
        out["crops"][crop] = rows
    return out


def _save_outlooks() -> None:
    """Persist weeks 2-4 and months 1-3 outlooks for every location."""
    origin = outlook.today().isoformat()
    rows = []
    for loc in [r["key"] for r in db.q("SELECT key FROM locations")]:
        w = outlook.weeks24(loc)
        for wk in w.get("weeks", []):
            for var in ("rain_total", "tmax_mean"):
                v = wk[var]
                rows.append((origin, loc, f"w{wk['week']}", var, v.get("p10"), v.get("p50"), v.get("p90"),
                             v.get("method"), "model" if v.get("method") == "model" else "climatology, not a forecast"))
        m = outlook.months13(loc)
        for mm in m.get("months", []):
            rows.append((origin, loc, f"m{mm['month']}", "rain_total", mm.get("p10"), mm.get("p50"), mm.get("p90"),
                         "climatology", "climatology"))
    with db.connect() as c:
        c.execute("DELETE FROM weather_outlook WHERE origin_date=?", (origin,))
        c.executemany("INSERT INTO weather_outlook VALUES(?,?,?,?,?,?,?,?,?)", rows)

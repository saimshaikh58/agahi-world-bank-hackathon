"""Run only the price backtests + final fits and write reports/backtest_price.csv. Usage: python scripts/backtest_price.py [fast|full]"""
from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from app import db
from app.forecast import registry
from app.util import now_iso

if __name__ == "__main__":
    db.migrate()
    mode = sys.argv[1] if len(sys.argv) > 1 else "fast"
    rid = db.x("INSERT INTO model_runs(started_at,mode,data_version) VALUES(?,?,?)", (now_iso(), mode, db.get_meta("data_version")))
    rows = registry.train_prices(rid, mode, lambda p, m: print(f"{p:5.0%} {m}"), lambda: False)
    db.x("UPDATE model_runs SET finished_at=?, summary_json=? WHERE id=?", (now_iso(), '{"price_only": true}', rid))
    for r in rows:
        print(f"{r['crop']:13s} {r['horizon']:4s} {r['chosen']:15s} {r['status']:13s} skill={r['skill']}")

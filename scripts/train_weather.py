"""Climatology + weeks 2-4 weather models only. Writes reports/backtest_weather.csv."""
from __future__ import annotations

import _bootstrap  # noqa: F401

from app import db
from app.util import now_iso
from app.weather import climatology, wmodels

if __name__ == "__main__":
    db.migrate()
    climatology.build_and_save()
    rid = db.x("INSERT INTO model_runs(started_at,mode,data_version) VALUES(?,?,?)", (now_iso(), "weather", db.get_meta("data_version")))
    rows = wmodels.train_weather_models(rid, lambda p, m: print(m), lambda: False)
    print(f"{sum(r['kept'] for r in rows)} of {len(rows)} weekly cells beat climatology by >= 3%")

"""Copy what a serverless deploy needs into deploy_assets/ (commit this folder):
- agahi_seed.db: the trained database (dataset, locations, forecasts, backtests, demo chats) without real
  farmers, sessions, messages or outbox rows
- models/: trained model files (the web app only reads the small NumPy intent model and weather files)
- reports/: evaluation reports for the Models page and README
Run after training, before every deploy:  python scripts/prepare_deploy.py"""
from __future__ import annotations

import shutil
import sqlite3
import sys

import _bootstrap  # noqa: F401

from app import db
from app.config import DEPLOY_DIR, MODELS_DIR, REPORTS_DIR, settings

RUNTIME_MODEL_GLOBS = ("intent/intent_lite.*", "weather/*.joblib", "price/*.json")


def main() -> int:
    if not settings.db_path.exists() or not db.q1("SELECT id FROM model_runs WHERE finished_at IS NOT NULL"):
        print("No trained models found. Run ./run.sh (or python scripts/train_all.py) first.")
        return 1
    if DEPLOY_DIR.exists():
        shutil.rmtree(DEPLOY_DIR)
    (DEPLOY_DIR / "models").mkdir(parents=True)
    seed = DEPLOY_DIR / "agahi_seed.db"
    src = sqlite3.connect(str(settings.db_path))
    dst = sqlite3.connect(str(seed))
    src.backup(dst)
    src.close()
    real = "SELECT phone FROM farmers WHERE demo=0"
    for sql in (f"DELETE FROM messages WHERE demo=0 OR phone IN ({real})", f"DELETE FROM sessions WHERE phone IN ({real})",
                "DELETE FROM farmers WHERE demo=0", "DELETE FROM outbox", "DELETE FROM webhook_log", "DELETE FROM alerts_log",
                "DELETE FROM weather_cache", "DELETE FROM broadcasts", "DELETE FROM jobs WHERE status != 'done'",
                "DELETE FROM meta WHERE key='sim_counter'", "DELETE FROM model_runs WHERE finished_at IS NULL"):
        dst.execute(sql)
    last = dst.execute("SELECT MAX(id) FROM model_runs WHERE finished_at IS NOT NULL").fetchone()[0]
    for table in ("backtest_preds", "backtest_results", "forecasts", "weather_backtest", "intent_eval"):
        sql = f"DELETE FROM {table} WHERE run_id != {int(last)}"
        dst.execute(sql)
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    n = 0
    for pattern in RUNTIME_MODEL_GLOBS:
        for p in MODELS_DIR.glob(pattern):
            target = DEPLOY_DIR / "models" / p.relative_to(MODELS_DIR)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
    clim = MODELS_DIR / "weather" / "climatology.joblib"
    if clim.exists():
        shutil.copy2(clim, DEPLOY_DIR / "models" / "weather" / "climatology.joblib")
    if REPORTS_DIR.exists():
        shutil.copytree(REPORTS_DIR, DEPLOY_DIR / "reports")
    size = sum(p.stat().st_size for p in DEPLOY_DIR.rglob("*") if p.is_file()) / 1e6
    print(f"deploy_assets ready: seed database, {n} model files, reports ({size:.1f} MB).")
    print("Next: git add deploy_assets && git commit -m 'Update deploy assets' && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())

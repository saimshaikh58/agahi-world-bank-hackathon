"""Idempotent first-run setup: folders, migrations, dataset, fast training, demo data. Always exits 0;
whatever fails is logged and shown in the dashboard."""
from __future__ import annotations

import logging
import traceback

import _bootstrap  # noqa: F401

from app import db, jobs
from app.config import ASSETS_DIR, BUNDLE_DIR, DATA_DIR, LOGS_DIR, MODELS_DIR, REPORTS_DIR, SAMPLE_DIR, settings
from app.logging_setup import setup_logging

REAL_BUNDLE = ASSETS_DIR / "kalimati_bundle.zip"


def step(name: str, fn) -> None:
    print(f"[first run] {name} ...", flush=True)
    try:
        fn()
        print(f"[first run] {name}: ok", flush=True)
    except Exception as e:  # keep going; the dashboard shows what is missing
        print(f"[first run] {name}: FAILED ({e}). The app will still start.", flush=True)
        logging.getLogger("agahi.first_run").error(traceback.format_exc())


def folders() -> None:
    for d in (DATA_DIR, BUNDLE_DIR, MODELS_DIR / "price", MODELS_DIR / "weather", MODELS_DIR / "intent", REPORTS_DIR, LOGS_DIR, SAMPLE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def dataset() -> None:
    if db.q1("SELECT id FROM dataset_versions WHERE active=1"):
        print("  dataset already loaded")
        return
    from app.ingest.bundle import ingest_path
    if REAL_BUNDLE.exists():
        rep = ingest_path(REAL_BUNDLE, is_sample=False)
        print(f"  loaded real Kalimati bundle: {len(rep.get('crops', []))} crops, prices {rep.get('date_range')}")
        return
    if not any(SAMPLE_DIR.glob("SAMPLE_*.csv")):
        from make_sample_data import generate
        generate(SAMPLE_DIR)
    ingest_path(SAMPLE_DIR, is_sample=True)
    print("  loaded SYNTHETIC sample data (banner will say so)")


def nlu_data() -> None:
    from app.core.intent_model import TRAIN_FILE
    if not TRAIN_FILE.exists():
        from make_nlu_data import main
        main()


def training() -> None:
    if db.q1("SELECT id FROM model_runs WHERE finished_at IS NOT NULL"):
        print("  models already trained")
        return
    from app.training import run_training
    jid = jobs.run_sync("train", run_training, {"mode": settings.train_mode})
    j = jobs.get(jid)
    print(f"  training {j['status']}" + (f": {j['error']}" if j["error"] else ""))


def demo() -> None:
    from app.seed import seed_demo
    n = seed_demo()
    print(f"  demo messages seeded: {n}" if n else "  demo data already present")


def main() -> None:
    setup_logging(logging.WARNING)
    step("folders", folders)
    step("database", db.migrate)
    step("dataset", dataset)
    step("NLU training data", nlu_data)
    step(f"train models ({settings.train_mode} mode, takes a few minutes the first time)", training)
    step("demo conversations", demo)
    print("[first run] done", flush=True)


if __name__ == "__main__":
    main()

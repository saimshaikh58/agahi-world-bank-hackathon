"""Cold start for serverless hosts (Vercel): the disk is empty except /tmp, so copy the prepared seed
database, trained models and reports from deploy_assets/ (made by scripts/prepare_deploy.py).
Locally this only runs migrations; scripts/first_run.py does the full setup."""
from __future__ import annotations

import logging
import shutil
import threading

from app import db
from app.config import ASSETS_DIR, DEPLOY_DIR, MODELS_DIR, REPORTS_DIR, settings

log = logging.getLogger("agahi.bootstrap")
SEED_DB = DEPLOY_DIR / "agahi_seed.db"
_lock = threading.Lock()
_ready = False


def _copy_tree(src, dst) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def ensure_ready() -> None:
    """Idempotent. Safe to call on every request."""
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        if settings.serverless:
            _serverless_start()
        db.migrate()
        _ready = True


def _serverless_start() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    fresh = False
    if not settings.db_path.exists() and SEED_DB.exists():
        shutil.copyfile(SEED_DB, settings.db_path)
        fresh = True
        log.info("Cold start: copied seed database")
    _copy_tree(DEPLOY_DIR / "models", MODELS_DIR)
    _copy_tree(DEPLOY_DIR / "reports", REPORTS_DIR)
    db.migrate()
    if fresh:  # the bundled data is older than today: let the first request fetch the missing days
        db.set_meta("fetch_day", "")
    if not db.q1("SELECT id FROM dataset_versions WHERE active=1"):
        bundle = ASSETS_DIR / "kalimati_bundle.zip"
        if bundle.exists():
            from app.ingest.bundle import ingest_path
            ingest_path(bundle, is_sample=False)
            log.warning("Cold start without deploy_assets: data loaded, models not trained. "
                        "Train locally, run scripts/prepare_deploy.py, redeploy.")

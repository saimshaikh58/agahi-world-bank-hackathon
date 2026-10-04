"""Train everything. Usage: python scripts/train_all.py [fast|full]"""
from __future__ import annotations

import sys

import _bootstrap  # noqa: F401

from app import db, jobs
from app.config import settings
from app.logging_setup import setup_logging
from app.training import run_training

if __name__ == "__main__":
    setup_logging()
    db.migrate()
    mode = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("fast", "full") else settings.train_mode
    jid = jobs.run_sync("train", run_training, {"mode": mode})
    j = jobs.get(jid)
    print(j["log"])
    sys.exit(0 if j["status"] == "done" else 1)

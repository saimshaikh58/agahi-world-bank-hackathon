"""Console + rotating file logging."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config import LOGS_DIR

_DONE = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once."""
    global _DONE
    if _DONE:
        return
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    fh = RotatingFileHandler(LOGS_DIR / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(ch)
    root.addHandler(fh)
    _DONE = True

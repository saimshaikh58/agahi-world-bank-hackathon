"""Ingest a data bundle. Usage: python scripts/ingest_zip.py path/to/bundle.zip [--sample]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from app import db
from app.ingest.bundle import IngestError, ingest_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    db.migrate()
    try:
        rep = ingest_path(Path(sys.argv[1]), is_sample="--sample" in sys.argv, force=True)
    except IngestError as e:
        print("ERROR:", e)
        sys.exit(1)
    print(json.dumps({k: rep.get(k) for k in ("version_id", "date_range", "warnings", "locations")}, indent=1, ensure_ascii=False))
    print("Now run: python scripts/train_all.py")

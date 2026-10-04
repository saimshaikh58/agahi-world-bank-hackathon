"""Read the production forecasts written by the latest model run."""
from __future__ import annotations

import json

import numpy as np

from app import db
from app.config import MODELS_DIR


def latest_run_id() -> int | None:
    """Id of the latest finished model run."""
    r = db.q1("SELECT id FROM model_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1")
    return r["id"] if r else None


def latest_forecasts() -> dict[tuple[str, str], dict]:
    """(crop, horizon) -> forecast row from the latest run."""
    rid = latest_run_id()
    if rid is None:
        return {}
    return {(r["crop"], r["horizon"]): r for r in db.q("SELECT * FROM forecasts WHERE run_id=?", (rid,))}


def footprint() -> dict:
    """Artifact sizes and inference latency from saved model metadata (no scikit-learn needed)."""
    files = []
    for p in sorted((MODELS_DIR / "price").glob("*.json")):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            files.append({"name": p.stem, "bytes": m.get("file_bytes", 0), "inference_ms": m.get("inference_ms", 0)})
        except ValueError:
            continue
    return {"price_files": len(files), "price_bytes": sum(f["bytes"] for f in files),
            "median_inference_ms": float(np.median([f["inference_ms"] for f in files])) if files else None,
            "largest": sorted(files, key=lambda f: -f["bytes"])[:5]}

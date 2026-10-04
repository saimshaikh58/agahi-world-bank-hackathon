"""Train the intent classifier only and print held-out accuracy."""
from __future__ import annotations

import _bootstrap  # noqa: F401

from app.core import intent_model, nlu

if __name__ == "__main__":
    ev = intent_model.train(nlu.normalise)
    print(f"held-out accuracy {ev['accuracy']:.3f}, by language {ev['by_lang']}, model {ev['file_bytes'] / 1024:.0f} KB")

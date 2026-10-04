"""Rewrite reports/model_card.md and the README 'Latest results' block from saved results."""
from __future__ import annotations

import _bootstrap  # noqa: F401

from app import reporting

if __name__ == "__main__":
    reporting.write_all()
    print("Updated reports/model_card.md and README.md results block")

"""Build agahi_hackathon.zip (root folder agahi_hackathon/) next to the project folder.
Excludes .venv, __pycache__, .env, logs, trained models, data/bundle contents and the local database."""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import _bootstrap  # noqa: F401

ROOT = _bootstrap.ROOT
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git", ".idea", ".vscode"}
EMPTY_KEEP = ["logs", "models/price", "models/weather", "models/intent", "data/bundle", "reports", "app/static/js/vendor"]


def wanted(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    parts = rel.parts
    if any(x in EXCLUDE_DIRS for x in parts):
        return False
    if parts[0] == "deploy_assets":
        return p.is_file()  # prepared for Vercel on purpose (seed database, models, reports)
    if rel.name in (".env", ".secret") or rel.suffix in (".db", ".db-wal", ".db-shm", ".pyc", ".zip") and rel.name != "kalimati_bundle.zip":
        return False
    if parts[0] in ("logs",) or (parts[0] == "models" and rel.name != ".gitkeep") or (parts[:2] == ("data", "bundle") and rel.name != ".gitkeep"):
        return False
    if parts[0] == "reports" and rel.name != ".gitkeep":
        return False
    if rel.name == "alias_overrides.json":
        return False
    return p.is_file()


def main() -> Path:
    out = ROOT.parent / "agahi_hackathon.zip" if len(sys.argv) < 2 else Path(sys.argv[1])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            if wanted(p):
                z.write(p, Path("agahi_hackathon") / p.relative_to(ROOT))
        for d in EMPTY_KEEP:
            name = f"agahi_hackathon/{d}/.gitkeep"
            if name not in z.namelist():
                z.writestr(name, "")
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    return out


if __name__ == "__main__":
    main()

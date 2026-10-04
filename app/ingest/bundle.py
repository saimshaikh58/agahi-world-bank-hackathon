"""Data bundle ingestion: safe unzip, detect files by column signature, validate, load, report."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from app import db, locations
from app.config import BUNDLE_DIR
from app.util import now_iso

log = logging.getLogger("agahi.ingest")
MAX_FILES = 60
MAX_TOTAL_UNCOMPRESSED = 600 * 1024 * 1024
MAX_RATIO = 200

SIGNATURES = [  # checked in order; first match wins
    ("prices_anchor", {"crop_group", "commodity_raw", "avg_price_kg", "carried_over"}),
    ("daily_by_crop", {"crop_group", "avg_price_kg", "n_variants"}),
    ("variant_coverage", {"days_with_price"}),
    ("weather", {"location", "tmin_c", "tmax_c", "rain_mm", "wind_ms", "heat_index_c"}),
    ("arrivals", {"arrival_qty"}),
    ("arrivals", {"arrival_kg"}),
    ("prices_raw", {"commodity_raw", "unit_raw", "avg_price"}),
]


class IngestError(Exception):
    """Fatal ingestion problem with a plain-English message."""


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract CSVs only, rejecting path traversal and zip bombs."""
    out: list[Path] = []
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise IngestError("The file is not a valid ZIP archive.") from e
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_FILES:
            raise IngestError(f"Too many files in ZIP ({len(infos)} > {MAX_FILES}).")
        total = sum(i.file_size for i in infos)
        if total > MAX_TOTAL_UNCOMPRESSED:
            raise IngestError("ZIP expands to more than the allowed size.")
        root = dest.resolve()
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or ":" in name:
                raise IngestError(f"Unsafe path in ZIP: {name}")
            if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO:
                raise IngestError(f"Suspicious compression ratio for {name}.")
            if not name.lower().endswith(".csv") or "/." in "/" + name:
                continue
            target = (root / name).resolve()
            if root not in target.parents:
                raise IngestError(f"Unsafe path in ZIP: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            out.append(target)
    return out


def read_csv(path: Path) -> pd.DataFrame:
    """Tolerant CSV read: BOM, header whitespace."""
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def detect(df: pd.DataFrame) -> str | None:
    """Detect the file kind from its columns."""
    cols = set(df.columns)
    for kind, sig in SIGNATURES:
        if sig <= cols:
            return kind
    return None


def _bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "t"])


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")


def clean_anchor(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the anchor price series and flag the primary variant per crop."""
    d = df.copy()
    d["date"] = _dates(d["date"])
    for c in ("min_price_kg", "max_price_kg", "avg_price_kg"):
        d[c] = _num(d.get(c, np.nan))
    d["carried_over"] = _bool(d["carried_over"])
    for c in ("origin", "size"):
        d[c] = d[c].fillna("").astype(str).str.strip() if c in d else ""
    d = d.dropna(subset=["date", "avg_price_kg"])
    d = d[(d["avg_price_kg"] > 0) & (d["avg_price_kg"] < 5000)]
    d["crop_group"] = d["crop_group"].astype(str).str.strip()
    d = d.drop_duplicates(subset=["date", "crop_group", "commodity_raw"], keep="last")
    counts = d[~d["carried_over"]].groupby(["crop_group", "commodity_raw"]).size().reset_index(name="n")
    primary = counts.sort_values("n", ascending=False).drop_duplicates("crop_group")
    pset = set(zip(primary["crop_group"], primary["commodity_raw"]))
    d["is_primary"] = [(a, b) in pset for a, b in zip(d["crop_group"], d["commodity_raw"])]
    return d


def clean_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Clean daily-by-crop aggregates."""
    d = df.copy()
    d["date"] = _dates(d["date"])
    for c in ("avg_price_kg", "min_price_kg", "max_price_kg", "n_variants", "arrivals_kg"):
        d[c] = _num(d[c]) if c in d else np.nan
    d["carried_over"] = _bool(d["carried_over"]) if "carried_over" in d else False
    d = d.dropna(subset=["date"]).drop_duplicates(subset=["date", "crop_group"], keep="last")
    return d


def clean_weather(df: pd.DataFrame) -> pd.DataFrame:
    """Clean weather rows."""
    d = df.copy()
    d["date"] = _dates(d["date"])
    d["location"] = d["location"].astype(str).str.strip()
    for c in ("tmin_c", "tmax_c", "rain_mm", "wind_ms", "heat_index_c"):
        d[c] = _num(d[c])
    d.loc[(d["rain_mm"] < 0) | (d["rain_mm"] > 500), "rain_mm"] = np.nan
    d = d.dropna(subset=["date"]).drop_duplicates(subset=["date", "location"], keep="last")
    return d


def _checksum(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda p: p.name):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _missing_days(dates: pd.Series) -> int:
    dt = pd.to_datetime(dates)
    if dt.empty:
        return 0
    return int((dt.max() - dt.min()).days + 1 - dt.nunique())


def ingest_path(path: Path, is_sample: bool = False, force: bool = False) -> dict:
    """Ingest a ZIP file or a folder of CSVs. Returns the data report."""
    path = Path(path)
    with tempfile.TemporaryDirectory() as tmp:
        if path.is_dir():
            files = sorted(p for p in path.rglob("*.csv") if not p.name.startswith("."))
        else:
            files = safe_extract(path, Path(tmp))
        if not files:
            raise IngestError("No CSV files found.")
        return _ingest_files(files, is_sample, force)


def _ingest_files(files: list[Path], is_sample: bool, force: bool) -> dict:
    checksum = _checksum(files)
    active = db.q1("SELECT * FROM dataset_versions WHERE active=1")
    if active and active["checksum"] == checksum and not force:
        rep = json.loads(active["report_json"])
        rep["skipped"] = "Same data as the active version; nothing changed."
        return rep
    found: dict[str, pd.DataFrame] = {}
    report: dict = {"files": [], "warnings": [], "created_at": now_iso(), "is_sample": is_sample}
    for p in files:
        try:
            df = read_csv(p)
        except Exception as e:  # unreadable file is a warning, not a crash
            report["warnings"].append(f"Could not read {p.name}: {e}")
            continue
        kind = detect(df)
        report["files"].append({"name": p.name, "kind": kind or "unknown", "rows": int(len(df)),
                                "columns": list(df.columns)[:12]})
        if kind and kind not in found:
            found[kind] = df
        elif kind is None:
            report["warnings"].append(f"{p.name}: columns not recognised, ignored.")
    if "prices_anchor" not in found and "daily_by_crop" not in found:
        raise IngestError("No price file found (need anchor series or daily-by-crop columns).")
    if "prices_anchor" in found:
        anchor = clean_anchor(found["prices_anchor"])
    else:
        report["warnings"].append("No anchor series file: using daily crop averages as the price series.")
        dd = clean_daily(found["daily_by_crop"])
        anchor = dd.rename(columns={})
        anchor["commodity_raw"] = "market average"
        anchor["origin"] = ""
        anchor["size"] = ""
        anchor["is_primary"] = True
        anchor = anchor.dropna(subset=["avg_price_kg"])
    daily = clean_daily(found["daily_by_crop"]) if "daily_by_crop" in found else None
    if daily is None or daily["arrivals_kg"].notna().sum() == 0:
        report["warnings"].append("No arrivals data: arrivals features are switched off.")
    weather = clean_weather(found["weather"]) if "weather" in found else None
    if weather is None:
        report["warnings"].append("No weather file: no farmer locations; weather uses no data.")
    _validate(anchor, report)
    version_id = _store(anchor, daily, weather, checksum, is_sample, report)
    return report | {"version_id": version_id}


def _validate(anchor: pd.DataFrame, report: dict) -> None:
    if anchor.empty:
        raise IngestError("Price file has no valid rows after cleaning.")
    report["date_range"] = [anchor["date"].min(), anchor["date"].max()]
    crops = []
    for crop, g in anchor[anchor["is_primary"]].groupby("crop_group"):
        crops.append({"crop": crop, "variant": str(g["commodity_raw"].iloc[0]), "days": int(len(g)),
                      "first": g["date"].min(), "last": g["date"].max(),
                      "missing_days": _missing_days(g["date"]),
                      "carried_over_share": round(float(g["carried_over"].mean()), 3)})
    report["crops"] = crops
    for c in crops:
        if c["days"] < 400:
            report["warnings"].append(f"{c['crop']}: only {c['days']} price days; forecasts may be unavailable.")


def _store(anchor: pd.DataFrame, daily: pd.DataFrame | None, weather: pd.DataFrame | None,
           checksum: str, is_sample: bool, report: dict) -> int:
    with db.connect() as c:
        c.execute("DELETE FROM prices")
        c.executemany(
            "INSERT OR REPLACE INTO prices VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(r.date, r.crop_group, str(r.commodity_raw), r.origin, r.size,
              None if pd.isna(r.min_price_kg) else float(r.min_price_kg),
              None if pd.isna(r.max_price_kg) else float(r.max_price_kg),
              float(r.avg_price_kg), int(r.carried_over), int(r.is_primary))
             for r in anchor.itertuples(index=False)])
        c.execute("DELETE FROM daily_crop")
        if daily is not None:
            c.executemany(
                "INSERT OR REPLACE INTO daily_crop VALUES(?,?,?,?,?,?,?,?)",
                [(r.date, r.crop_group, _f(r.avg_price_kg), _f(r.min_price_kg), _f(r.max_price_kg),
                  _f(r.n_variants), int(bool(r.carried_over)), _f(r.arrivals_kg))
                 for r in daily.itertuples(index=False)])
        c.execute("DELETE FROM weather")
        if weather is not None:
            c.executemany(
                "INSERT OR REPLACE INTO weather VALUES(?,?,?,?,?,?,?)",
                [(r.date, r.location, _f(r.tmin_c), _f(r.tmax_c), _f(r.rain_mm), _f(r.wind_ms), _f(r.heat_index_c))
                 for r in weather.itertuples(index=False)])
    keys = sorted(weather["location"].unique().tolist()) if weather is not None else []
    rows = locations.build_locations(keys)
    locations.save_locations(rows)
    report["locations"] = [{"key": r["key"], "name": r["name_en"], "selectable": bool(r["selectable"]),
                            "has_coords": r["lat"] is not None} for r in rows]
    if weather is not None:
        report["weather_coverage"] = [
            {"location": k, "rows": int(len(g)), "first": g["date"].min(), "last": g["date"].max(),
             "missing_days": _missing_days(g["date"]), "rain_missing": int(g["rain_mm"].isna().sum())}
            for k, g in weather.groupby("location")]
    with db.connect() as c:
        c.execute("UPDATE dataset_versions SET active=0")
        cur = c.execute("INSERT INTO dataset_versions(created_at,checksum,is_sample,path,report_json,active) "
                        "VALUES(?,?,?,?,?,1)", (now_iso(), checksum, int(is_sample), "", "{}"))
        vid = int(cur.lastrowid)
    out = BUNDLE_DIR / f"v{vid}"
    out.mkdir(parents=True, exist_ok=True)
    anchor.to_csv(out / "prices_anchor.csv", index=False)
    if daily is not None:
        daily.to_csv(out / "daily_by_crop.csv", index=False)
    if weather is not None:
        weather.to_csv(out / "weather.csv", index=False)
    report["version_id"] = vid
    db.x("UPDATE dataset_versions SET path=?, report_json=? WHERE id=?", (str(out), json.dumps(report), vid))
    db.set_meta("data_version", vid)
    db.set_meta("is_sample", bool(is_sample))
    log.info("Ingested dataset v%s (%s crops, %s locations)", vid, len(report.get("crops", [])), len(keys))
    return vid


def _f(v) -> float | None:
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None

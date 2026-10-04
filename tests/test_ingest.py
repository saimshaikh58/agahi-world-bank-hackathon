import io
import shutil
import zipfile

import pandas as pd
import pytest

from app import locations
from app.core import data
from app.core.engine import handle_message
from app.ingest import bundle
from app.ingest.bundle import IngestError, ingest_path
from conftest import SAMPLE, TMP


@pytest.fixture()
def restore():
    yield
    ingest_path(SAMPLE, is_sample=True, force=True)
    data.invalidate()


def _zip(path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return path


def test_detect_by_columns_with_renamed_files(restore):
    files = {f"x/{i}_renamed.csv": (SAMPLE / n).read_text(encoding="utf-8") for i, n in
             enumerate(["SAMPLE_weather_daily.csv", "SAMPLE_anchor_series.csv", "SAMPLE_daily_by_crop.csv"])}
    rep = ingest_path(_zip(TMP / "renamed.zip", files), force=True)
    kinds = {f["kind"] for f in rep["files"]}
    assert {"prices_anchor", "daily_by_crop", "weather"} <= kinds


def test_rejects_path_traversal():
    with pytest.raises(IngestError):
        ingest_path(_zip(TMP / "evil.zip", {"../evil.csv": "a,b\n1,2\n"}))


def test_rejects_oversized(monkeypatch):
    monkeypatch.setattr(bundle, "MAX_TOTAL_UNCOMPRESSED", 100)
    with pytest.raises(IngestError):
        ingest_path(_zip(TMP / "big.zip", {"a.csv": "x" * 1000}))


def test_missing_optional_files_are_warnings(restore):
    rep = ingest_path(_zip(TMP / "anchor_only.zip", {"a.csv": (SAMPLE / "SAMPLE_anchor_series.csv").read_text(encoding="utf-8")}), force=True)
    text = " ".join(rep["warnings"])
    assert "arrivals" in text and "weather" in text.lower()


def test_locations_come_from_weather_file(restore, fresh_phone):
    w = pd.read_csv(SAMPLE / "SAMPLE_weather_daily.csv")
    w = w[w["location"].isin(["boundary_mean", "kathmandu_valley"])].copy()
    w.loc[w["location"] == "kathmandu_valley", "location"] = "alpha_town"
    files = {"w.csv": w.to_csv(index=False), "a.csv": (SAMPLE / "SAMPLE_anchor_series.csv").read_text(encoding="utf-8")}
    ingest_path(_zip(TMP / "alpha.zip", files), force=True)
    data.invalidate()
    keys = [l["key"] for l in locations.selectable()]
    assert keys == ["alpha_town"]
    assert locations.get("alpha_town")["lat"] is None
    r = handle_message("web", fresh_phone, "1", offline=True)
    assert "Alpha" in r.text
    r = handle_message("web", fresh_phone, "1", offline=True)
    r = handle_message("web", fresh_phone, "3", offline=True)
    r = handle_message("web", fresh_phone, "1", offline=True)
    assert "Purano data matra" in r.text and "herera anuman" in r.text  # history only, labelled

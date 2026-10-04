"""Test setup: every output goes to a temporary folder; no network; small synthetic dataset."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agahi_test_"))
os.environ.update({
    "AGAHI_DB": str(TMP / "test.db"), "AGAHI_MODELS_DIR": str(TMP / "models"), "AGAHI_REPORTS_DIR": str(TMP / "reports"),
    "AGAHI_LOGS_DIR": str(TMP / "logs"), "AGAHI_BUNDLE_DIR": str(TMP / "bundle"), "LIVE_WEATHER": "0",
    "ADMIN_PASSWORD": "test-pass", "SECRET_KEY": "test-secret", "SMS_PROVIDER": "mock", "SMS_WEBHOOK_SECRET": "",
    "RATE_PER_MIN": "20",
})
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from app import db  # noqa: E402

SAMPLE = TMP / "sample"


@pytest.fixture(scope="session", autouse=True)
def dataset():
    """Synthetic dataset ingested once; intent model trained into the temp folder."""
    from make_sample_data import generate

    from app.core import intent_model, nlu
    from app.ingest.bundle import ingest_path
    db.migrate()
    generate(SAMPLE)
    ingest_path(SAMPLE, is_sample=True)
    intent_model.train(nlu.normalise)
    yield


@pytest.fixture()
def fresh_phone():
    """A unique simulator number, cleaned up afterwards."""
    from app.core.engine import reset_session
    fresh_phone.n = getattr(fresh_phone, "n", 0) + 1
    phone = f"+97798000{90000 + fresh_phone.n}"
    reset_session(phone)
    yield phone
    reset_session(phone)

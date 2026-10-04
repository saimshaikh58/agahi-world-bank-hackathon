"""Daily Kalimati fetch with the HTTP part mocked."""
import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.ingest import fetch_latest
from app.main import app


class FakeFetcher:
    """Returns a site-like table for each day: Nepali names, unit, min, max, avg."""

    def __init__(self, variants, fail=False, kind="prices"):
        self.variants, self.fail, self.kind, self.calls = variants, fail, kind, 0

    def fetch(self, d):
        self.calls += 1
        if self.fail:
            raise RuntimeError("connection timed out")
        k = d.toordinal() % 7
        if self.kind == "arrivals":
            return pd.DataFrame({"name": [v for _, v in self.variants], "unit": ["के.जी."] * len(self.variants),
                                 "qty": [1000 + 10 * k] * len(self.variants)})
        return pd.DataFrame({"name": [v for _, v in self.variants], "unit": ["के.जी."] * len(self.variants),
                             "min": [20 + k] * len(self.variants), "max": [40 + k] * len(self.variants),
                             "avg": [30 + k + i for i in range(len(self.variants))]})


@pytest.fixture()
def setup(monkeypatch):
    """Latest stored day is 3 days before 'today'; fetcher returns the primary variant of each known crop
    whose name the owner's crop rules recognise."""
    snapshot = {t: db.q(f"SELECT * FROM {t}") for t in ("prices", "daily_crop", "forecasts", "forecast_ledger")}
    latest = db.q1("SELECT MAX(date) AS d FROM prices")["d"]
    today = dt.date.fromisoformat(latest) + dt.timedelta(days=3)
    monkeypatch.setattr(fetch_latest, "kathmandu_today", lambda: today)
    db.set_meta("fetch_empty_days", [])
    db.set_meta("fetch_day_hash", {})
    variants = [(r["crop"], r["variant"]) for r in
                db.q("SELECT DISTINCT crop, variant FROM prices WHERE is_primary=1")
                if fetch_latest.classify(r["variant"]) == r["crop"]]
    if not variants:   # synthetic names may not match the crop rules: rename two variants to real Nepali names
        for crop, name in (("tomato", "गोलभेडा ठूलो(नेपाली)"), ("potato", "आलु रातो")):
            db.x("UPDATE prices SET variant=? WHERE crop=? AND is_primary=1", (name, crop))
            variants.append((crop, name))
    yield {"variants": variants, "latest": latest, "today": today}
    with db.connect() as c:
        for t, rows in snapshot.items():
            c.execute(f"DELETE FROM {t}")
            if rows:
                cols = list(rows[0])
                c.executemany(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                              [tuple(r[k] for k in cols) for r in rows])
    from app.core import data
    data.invalidate()


def fetchers(s, fail=False):
    return {"prices": FakeFetcher(s["variants"], fail), "arrivals": FakeFetcher(s["variants"], fail, "arrivals")}


def count():
    return db.q1("SELECT COUNT(*) AS n FROM prices")["n"]


def test_new_rows_added_once_then_nothing(setup):
    before = count()
    r1 = fetch_latest.run(fetchers=fetchers(setup))
    assert r1["ok"] and r1["rows_added"] > 0, r1
    assert r1["latest_date"] == setup["today"].isoformat()
    assert count() > before
    mid = count()
    r2 = fetch_latest.run(fetchers=fetchers(setup))
    assert r2["rows_added"] == 0 and count() == mid
    # the new day is "today" for the bot and the forecasts start from it
    from app.core import data
    assert str(data.store().today)[:10] == setup["today"].isoformat()
    row = db.q1("SELECT origin_date FROM forecasts WHERE status<>'unavailable' AND p50 IS NOT NULL LIMIT 1")
    if row:
        assert row["origin_date"] == setup["today"].isoformat()


def test_failure_leaves_data_unchanged(setup):
    before = db.q("SELECT * FROM prices ORDER BY date, crop, variant")
    r = fetch_latest.run(fetchers=fetchers(setup, fail=True))
    assert r["ok"] is False and "Old data is kept" in r["error"]
    assert db.q("SELECT * FROM prices ORDER BY date, crop, variant") == before
    assert db.get_meta("fetch_last")["ok"] is False


def test_day_change_trigger_runs_once(setup, monkeypatch):
    db.set_meta("fetch_day", "")
    assert fetch_latest.claim_today() is True
    assert fetch_latest.claim_today() is False
    calls = []
    monkeypatch.setattr(settings, "auto_fetch", True)
    monkeypatch.setattr(fetch_latest, "run", lambda **kw: calls.append(1) or {})
    monkeypatch.setattr(settings, "serverless", True)   # inline, so the call is counted before the response
    db.set_meta("fetch_day", "")
    with TestClient(app) as c:
        c.get("/")
        c.get("/chat")
        c.get("/")
    assert len(calls) == 1


def test_endpoint_rejects_bad_token(setup, monkeypatch):
    monkeypatch.setattr(fetch_latest, "run", lambda **kw: {"ok": True, "rows_added": 0})
    with TestClient(app) as c:
        assert c.post("/api/jobs/fetch").status_code == 401
        assert c.post("/api/jobs/fetch", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/jobs/fetch", headers={"Authorization": "Bearer fetch-token"}).status_code == 200

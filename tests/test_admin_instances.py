"""Admin keeps working across serverless instances, after a purge, with real (non-sample) data and no demo rows."""
import pytest
from fastapi.testclient import TestClient

from app import bootstrap, config, db, seed
from app.config import settings
from app.core import data
from app.main import app

ADMIN_GETS = ("/api/admin/me", "/api/admin/status", "/api/admin/overview", "/api/admin/conversations",
              "/api/admin/market", "/api/admin/models", "/api/admin/weather", "/api/admin/data",
              "/api/admin/syscheck", "/api/admin/farmers", "/api/admin/farmers.csv", "/api/admin/broadcasts",
              "/api/admin/sms", "/api/admin/quality")


def new_instance(monkeypatch):
    """What a fresh serverless instance does: no in-memory state, key worked out again from the environment."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(settings, "secret_key", config._secret(settings.admin_password))
    monkeypatch.setattr(bootstrap, "_ready", False)
    data.invalidate()
    return TestClient(app)


@pytest.fixture()
def real_data():
    ds = db.q1("SELECT id, is_sample FROM dataset_versions WHERE active=1")
    db.x("UPDATE dataset_versions SET is_sample=0 WHERE id=?", (ds["id"],))
    db.set_meta("is_sample", False)
    data.invalidate()
    yield
    db.x("UPDATE dataset_versions SET is_sample=? WHERE id=?", (ds["is_sample"], ds["id"]))
    db.set_meta("is_sample", bool(ds["is_sample"]))
    data.invalidate()


def test_key_is_stable_without_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    a, b = config._secret("pw-one"), config._secret("pw-one")
    assert a == b and a != config._secret("pw-two")
    monkeypatch.setenv("SECRET_KEY", "explicit")
    assert config._secret("pw-one") == "explicit"


def test_login_purge_then_every_admin_api_on_new_instances(monkeypatch, real_data):
    c1 = new_instance(monkeypatch)
    r = c1.post("/api/admin/login", json={"password": "test-pass"})
    assert r.status_code == 200
    csrf, cookie = r.json()["csrf"], c1.cookies.get("agahi_admin")
    seed.seed_demo(n_farmers=5, force=True)
    c2 = new_instance(monkeypatch)
    c2.cookies.set("agahi_admin", cookie)
    r = c2.post("/api/admin/demo/purge", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert seed.demo_rows() == 0
    assert db.q1("SELECT COUNT(*) AS n FROM prices")["n"] > 0           # real data untouched
    for path in ADMIN_GETS:
        c = new_instance(monkeypatch)
        c.cookies.set("agahi_admin", cookie)
        r = c.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        assert '"demo": 1' not in r.text
    c3 = new_instance(monkeypatch)
    c3.cookies.set("agahi_admin", cookie)
    assert c3.get("/admin").status_code == 200


def test_lockout_is_shared_between_instances(monkeypatch):
    db.x("DELETE FROM login_fails")
    for _ in range(5):
        assert new_instance(monkeypatch).post("/api/admin/login", json={"password": "wrong"}).status_code == 401
    r = new_instance(monkeypatch).post("/api/admin/login", json={"password": "test-pass"})
    assert r.status_code == 429
    db.x("DELETE FROM login_fails")


def test_cookie_flags():
    with TestClient(app, base_url="https://testserver") as c:
        db.x("DELETE FROM login_fails")
        r = c.post("/api/admin/login", json={"password": "test-pass"})
        sc = r.headers.get("set-cookie", "").lower()
        assert "httponly" in sc and "samesite" in sc and "secure" in sc

import pytest
from fastapi.testclient import TestClient

from app.core.engine import handle_message
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def login(c):
    r = c.post("/api/admin/login", json={"password": "test-pass"})
    assert r.status_code == 200
    return r.json()["csrf"]


def test_requires_login(client):
    r = client.get("/api/admin/status")
    assert r.status_code == 401 and r.json()["error"]["code"] == "not_logged_in"


def test_wrong_password(client):
    assert client.post("/api/admin/login", json={"password": "nope"}).status_code == 401


def test_csrf_enforced(client):
    csrf = login(client)
    assert client.post("/api/admin/test/new-farmer", json={}).status_code == 403
    assert client.post("/api/admin/test/new-farmer", json={}, headers={"X-CSRF-Token": csrf}).status_code == 200


def test_phones_masked_everywhere(client):
    handle_message("web", "+9779812341234", "hello", offline=True)
    login(client)
    for path in ("/api/admin/farmers", "/api/admin/conversations", "/api/admin/sms"):
        body = client.get(path).text
        assert "9812341234" not in body, path
    csv = client.get("/api/admin/farmers.csv").text
    assert "9812341234" not in csv and "+977-98****1234" in csv


def test_admin_pages_respond(client):
    login(client)
    for p in ("/api/admin/overview?range=30d", "/api/admin/market", "/api/admin/models", "/api/admin/weather",
              "/api/admin/data", "/api/admin/quality", "/api/admin/test/template-check", "/health", "/", "/admin"):
        assert client.get(p).status_code == 200, p


def test_error_shape(client):
    r = client.post("/api/chat/send", json={"phone": "+9779800000001"})
    assert r.status_code == 400 and "error" in r.json()

import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.core import engine
from app.main import app
from app.sms import alerts, outbox
from app.sms.base import sign


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def post(client, body, secret=None):
    raw = json.dumps(body).encode()
    h = {"Content-Type": "application/json"}
    if secret:
        h["X-Agahi-Signature"] = sign(secret, raw)
    return client.post("/api/sms/inbound", content=raw, headers=h)


def test_bad_signature_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "sms_webhook_secret", "s3cret")
    assert post(client, {"from": "9841000001", "text": "hi", "id": "a1"}, "wrong").status_code == 403
    assert post(client, {"from": "9841000001", "text": "hi", "id": "a2"}, "s3cret").status_code == 200


def test_duplicate_processed_once(client):
    b = {"from": "9841000002", "text": "hello", "id": "dup-1"}
    assert post(client, b).json()["queued"] == 1
    assert post(client, b).json()["queued"] == 0


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_per_min", 3)
    engine.reset_rate()
    texts = [post(client, {"from": "9841000003", "text": "hi", "id": f"rl{i}"}) for i in range(4)]
    assert all(t.status_code == 200 for t in texts)
    last = db.q1("SELECT text FROM outbox WHERE phone='+9779841000003' ORDER BY id DESC LIMIT 1")
    assert last["text"].startswith("Agahi: dherai SMS")


def test_stop_blocks_alerts_start_resumes(monkeypatch):
    phone = "+9779841000004"
    for t in ("1", "1"):
        engine.handle_message("sms", phone, t, offline=True)
    monkeypatch.setattr(alerts, "_alert_for", lambda f, ctx, off: "Agahi alert: test")
    engine.handle_message("sms", phone, "stop", offline=True)
    db.x("DELETE FROM alerts_log")
    alerts.run_alerts(respect_quiet=False)
    assert not db.q1("SELECT id FROM outbox WHERE phone=? AND kind='alert'", (phone,))
    engine.handle_message("sms", phone, "start", offline=True)
    alerts.run_alerts(respect_quiet=False)
    assert db.q1("SELECT id FROM outbox WHERE phone=? AND kind='alert'", (phone,))


def test_retry_then_fail_after_three():
    oid = outbox.enqueue("+9779841000005", "FAILTEST message", "operator")
    for _ in range(3):
        db.x("UPDATE outbox SET next_attempt_at=? WHERE id=?", ("2000-01-01T00:00:00+05:45", oid))
        outbox.process_once()
    row = db.q1("SELECT status, attempts FROM outbox WHERE id=?", (oid,))
    assert row["status"] == "failed" and row["attempts"] == 3


def test_idempotency_prevents_double_send():
    a = outbox.enqueue("+9779841000006", "hello", "alert", idem="k-1")
    b = outbox.enqueue("+9779841000006", "hello", "alert", idem="k-1")
    assert a == b


def test_delivery_receipt(client):
    import time
    oid = outbox.enqueue("+9779841000007", "hi there", "operator")
    for _ in range(40):  # the app's own background worker may pick it up first
        outbox.process_once()
        pid = db.q1("SELECT provider_msg_id, status FROM outbox WHERE id=?", (oid,))
        if pid["status"] == "delivered":
            break
        time.sleep(0.05)
    assert pid["status"] == "delivered"
    r = client.post("/api/sms/status", json={"id": pid["provider_msg_id"], "status": "failed"})
    assert r.status_code == 200
    assert db.q1("SELECT status FROM outbox WHERE id=?", (oid,))["status"] == "failed"

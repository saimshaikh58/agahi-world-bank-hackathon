from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app import db, http
from app.config import settings
from app.main import app
from app.sms import outbox
from app.sms.mock import MockProvider
from app.sms.twilio import TwilioProvider, signature, twiml

BASE = "https://agahi.example.org"


@pytest.fixture()
def tw(monkeypatch):
    monkeypatch.setattr(settings, "twilio_sid", "ACtest")
    monkeypatch.setattr(settings, "twilio_token", "secret-token")
    monkeypatch.setattr(settings, "twilio_from", "+15005550006")
    monkeypatch.setattr(settings, "public_base_url", BASE)
    monkeypatch.setattr(settings, "sms_verify_signature", True)
    outbox.set_provider(TwilioProvider(settings))
    with TestClient(app) as c:
        yield c
    outbox.set_provider(MockProvider(settings))


def post(c, params, path="/api/sms/inbound", good=True):
    sig = signature("secret-token", BASE + path, params) if good else "bad"
    return c.post(path, content=urlencode(params), headers={"Content-Type": "application/x-www-form-urlencoded",
                                                            "X-Twilio-Signature": sig})


def msg(text, sid, frm="+15551234567"):
    return {"From": frm, "To": "+15005550006", "Body": text, "MessageSid": sid, "AccountSid": "ACtest"}


def test_bad_signature_rejected(tw):
    r = post(tw, msg("hello", "SM-bad"), good=False)
    assert r.status_code == 403 and r.headers["content-type"].startswith("text/xml")


def test_valid_signature_replies_with_twiml(tw):
    r = post(tw, msg("hello", "SM-1"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/xml")
    assert r.text.startswith('<?xml') and "<Message" in r.text and "Agahi" in r.text
    row = db.q1("SELECT status, kind, provider FROM outbox WHERE phone='+15551234567' ORDER BY id DESC")
    assert row["status"] == "sent" and row["provider"] == "twilio"


def test_plus_numbers_kept_as_is(tw):
    post(tw, msg("hi", "SM-plus", "+447700900123"))
    assert db.q1("SELECT phone FROM farmers WHERE phone='+447700900123'")


def test_duplicate_message_sid_empty_response(tw):
    assert "<Message" in post(tw, msg("hello", "SM-dup")).text
    second = post(tw, msg("hello", "SM-dup"))
    assert second.status_code == 200 and "<Message" not in second.text and "<Response/>" in second.text


def test_twiml_escaping():
    x = twiml("Price < 5 & > 2 \"ok\"\n1 Menu")
    assert "&lt; 5 &amp; &gt; 2" in x and "\n1 Menu" in x
    assert twiml(None).endswith("<Response/>")


def test_rest_send_and_status_callback(tw, monkeypatch):
    calls = {}

    def fake_post(url, data=None, json_body=None, headers=None, auth=None, timeout=5.0):
        calls.update(url=url, data=data, auth=auth)
        return 201, '{"sid": "SMrest1", "status": "queued"}'
    monkeypatch.setattr(http, "post", fake_post)
    oid = outbox.enqueue("+15551230000", "Agahi test\n1 Menu", "operator")
    outbox.process_once()
    assert calls["url"].endswith("/Accounts/ACtest/Messages.json")
    assert calls["data"]["From"] == "+15005550006" and calls["data"]["To"] == "+15551230000"
    assert calls["data"]["StatusCallback"] == BASE + "/api/sms/status" and calls["auth"] == ("ACtest", "secret-token")
    assert db.q1("SELECT status FROM outbox WHERE id=?", (oid,))["status"] == "sent"
    r = post(tw, {"MessageSid": "SMrest1", "MessageStatus": "delivered"}, "/api/sms/status")
    assert r.status_code == 200
    assert db.q1("SELECT status FROM outbox WHERE id=?", (oid,))["status"] == "delivered"


def test_rest_send_failure_is_retried(tw, monkeypatch):
    monkeypatch.setattr(http, "post", lambda *a, **k: (400, '{"message": "The To number is not verified"}'))
    oid = outbox.enqueue("+15551230001", "hi", "operator")
    outbox.process_once()
    row = db.q1("SELECT status, error FROM outbox WHERE id=?", (oid,))
    assert row["status"] == "queued" and "not verified" in row["error"]


def test_stop_and_start(tw):
    phone = "+15551239999"
    for i, t in enumerate(["1", "1"]):
        post(tw, msg(t, f"SM-ss{i}", phone))
    post(tw, msg("STOP", "SM-stop", phone))
    assert db.q1("SELECT subscribed FROM farmers WHERE phone=?", (phone,))["subscribed"] == 0
    post(tw, msg("START", "SM-start", phone))
    assert db.q1("SELECT subscribed FROM farmers WHERE phone=?", (phone,))["subscribed"] == 1


def test_forwarded_host_used_when_no_base_url(tw, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    params = msg("hello", "SM-fwd")
    sig = signature("secret-token", "https://my-app.vercel.app/api/sms/inbound", params)
    r = tw.post("/api/sms/inbound", content=urlencode(params), headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": sig,
        "X-Forwarded-Proto": "https", "X-Forwarded-Host": "my-app.vercel.app"})
    assert r.status_code == 200 and "<Message" in r.text


def test_e164_and_ready_flags():
    from app.config import _e164, twilio_ready
    assert _e164("+1 (415) 555-0100") == "+14155550100" and _e164("") == ""
    flags = twilio_ready(settings)
    assert set(flags) == {"TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "PUBLIC_BASE_URL"}
    assert all(isinstance(v, bool) for v in flags.values())


def test_secure_cookie_over_https():
    with TestClient(app, base_url="https://agahi.example.org") as c:
        r = c.post("/api/admin/login", json={"password": "test-pass"})
        assert "secure" in r.headers["set-cookie"].lower()

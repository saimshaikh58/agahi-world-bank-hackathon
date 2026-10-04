"""SMS webhooks: inbound messages and delivery receipts; alerts job trigger.
Twilio gets TwiML (text/xml) back; other providers get JSON."""
from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api import auth
from app.api.errors import ApiError
from app.config import settings
from app.sms import alerts, outbox
from app.sms.inbound import SignatureError, handle_inbound, handle_status
from app.sms.twilio import twiml

router = APIRouter()
MAX_BODY = 64 * 1024


async def _read(request: Request) -> tuple[bytes, dict]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ApiError(413, "too_large", "Webhook body too large.")
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "bad_json", "Body is not valid JSON.")
    else:
        data = dict(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))
    if not isinstance(data, dict):
        raise ApiError(400, "bad_body", "Expected a JSON object or form fields.")
    return raw, data


def public_url(request: Request) -> str:
    """The URL the provider called (needed for Twilio signatures).
    PUBLIC_BASE_URL wins; otherwise X-Forwarded-Proto/Host (Vercel, proxies); otherwise the request URL."""
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if settings.public_base_url:
        return settings.public_base_url + path
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{proto}://{host}{path}"


def _base(request: Request) -> str:
    url = public_url(request)
    return url[: url.index("/api/")]


def _xml(body: str, status: int = 200) -> Response:
    return Response(body, status_code=status, media_type="text/xml")


@router.post("/api/sms/inbound")
async def sms_inbound(request: Request):
    raw, data = await _read(request)
    headers = {k.lower(): v for k, v in request.headers.items()}
    inline = outbox.provider().reply_inline
    try:
        res = handle_inbound(raw, headers, public_url(request), data)
    except SignatureError as e:
        if inline:
            return _xml(twiml(None), 403)
        raise ApiError(403, "bad_signature", str(e))
    if inline:
        action = f"{_base(request)}/api/sms/status?oid={res.outbox_id}" if res.outbox_id else None
        return _xml(twiml(res.inline_text, action))
    return {"ok": True, "queued": res.queued}


@router.post("/api/sms/status")
async def sms_status(request: Request, oid: int | None = None):
    raw, data = await _read(request)
    headers = {k.lower(): v for k, v in request.headers.items()}
    inline = outbox.provider().reply_inline
    try:
        handle_status(raw, headers, public_url(request), data, oid)
    except SignatureError as e:
        if inline:
            return _xml(twiml(None), 403)
        raise ApiError(403, "bad_signature", str(e))
    if inline:
        return _xml(twiml(None))
    return {"ok": True}


@router.post("/api/jobs/alerts")
def jobs_alerts(request: Request) -> dict:
    """Run the alerts job. Allowed with 'Authorization: Bearer <ALERTS_TOKEN>' (cron, Vercel) or an admin session."""
    sent = request.headers.get("authorization", "")
    if settings.alerts_token and hmac.compare_digest(sent, f"Bearer {settings.alerts_token}"):
        out = alerts.run_alerts()
    else:
        auth.require_admin(request)
        out = alerts.run_alerts()
    if settings.serverless:
        outbox.process_once()
    return out


@router.api_route("/api/jobs/fetch", methods=["GET", "POST"])
def jobs_fetch(request: Request) -> dict:
    """Fetch new Kalimati days. 'Authorization: Bearer <FETCH_TOKEN>' (Vercel Cron sends CRON_SECRET this way)
    or an admin session. Wrong or missing token: 401."""
    from app.ingest import fetch_latest
    sent = request.headers.get("authorization", "")
    if not (settings.fetch_token and hmac.compare_digest(sent, f"Bearer {settings.fetch_token}")):
        auth.require_admin(request)
    return fetch_latest.run()

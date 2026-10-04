"""FastAPI app: routes, error handlers, startup (migrations, outbox worker)."""
from __future__ import annotations

import asyncio
import threading
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Vercel loads this file directly; make sure the project root is importable as the 'app' package.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import bootstrap, db, jobs
from app.api import admin_api
from app.api.errors import ApiError, error_response
from app.channels import sms_routes, web
from app.config import STATIC_DIR, settings, twilio_ready
from app.core import data
from app.logging_setup import setup_logging
from app.sms import outbox

log = logging.getLogger("agahi")
VERSION = "1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    bootstrap.ensure_ready()
    stop = asyncio.Event()
    task = None
    if settings.serverless:
        log.info("Serverless mode: no outbox worker and no training. Train locally, run prepare_deploy, redeploy.")
    else:
        jobs.recover_stale()
        task = asyncio.create_task(outbox.worker(stop))
    if settings.sms_provider == "twilio":
        missing = [k for k, ok in twilio_ready(settings).items() if not ok]
        if missing:
            log.warning("SMS_PROVIDER=twilio but these are not set: %s", ", ".join(missing))
    if settings.serverless and not os.environ.get("SECRET_KEY"):
        log.info("No SECRET_KEY set: admin sessions are signed with a key derived from ADMIN_PASSWORD.")
    if settings.admin_password == "agahi-admin":
        log.warning("Default admin password in use. Set ADMIN_PASSWORD in .env before sharing.")
    yield
    stop.set()
    if task:
        await task


app = FastAPI(title="Agahi | agahi_hackathon", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
@app.middleware("http")
async def ready(request: Request, call_next):
    """Serverless hosts may skip lifespan events, so make sure setup ran before the first request."""
    bootstrap.ensure_ready()
    _maybe_fetch(request)
    return await call_next(request)


def _maybe_fetch(request: Request) -> None:
    """First request of a new Asia/Kathmandu day starts one fetch of missing days (DB lock, all instances).
    Local server: in a background thread. Serverless (no background threads): inline, small and time-limited."""
    if not settings.auto_fetch or request.url.path.startswith(("/static", "/api/jobs/fetch", "/healthz")):
        return
    try:
        from app.ingest import fetch_latest
        if not db.q1("SELECT id FROM dataset_versions WHERE active=1") or not fetch_latest.claim_today():
            return
        if settings.serverless:
            fetch_latest.run(budget_s=8.0, chunk=3)
        else:
            threading.Thread(target=fetch_latest.run, daemon=True).start()
    except Exception:  # a fetch problem must never break a page
        log.exception("daily fetch trigger failed")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(web.router)
app.include_router(admin_api.public)
app.include_router(admin_api.router)
app.include_router(sms_routes.router)


@app.exception_handler(ApiError)
async def api_error(_: Request, e: ApiError):
    return error_response(e.status, e.code, e.message)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    first = e.errors()[0] if e.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return error_response(400, "invalid_input", f"Invalid input{(' for ' + where) if where else ''}: {first.get('msg', '')}")


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, e: StarletteHTTPException):
    return error_response(e.status_code, "http_error", str(e.detail))


@app.exception_handler(Exception)
async def unhandled(_: Request, e: Exception):
    log.exception("Unhandled error: %s", e)
    return error_response(500, "internal", "Something went wrong on the server. Details are in logs/app.log.")


@app.get("/health")
def health() -> dict:
    try:
        s = data.store()
        ok_db, ok_data, ok_models = True, s.today is not None, s.run_id is not None
    except Exception:  # health must answer even if the DB is broken
        ok_db = ok_data = ok_models = False
    return {"status": "ok" if ok_db else "degraded", "db": ok_db, "dataset": ok_data, "models": ok_models, "version": VERSION}

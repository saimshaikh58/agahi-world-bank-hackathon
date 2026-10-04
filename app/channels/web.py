"""Web pages (chat simulator, admin) and the public simulator chat API."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app import brand, db, locations
from app.api.admin_api import SIM_PREFIX, new_sim_phone
from app.api.errors import ApiError
from app.config import TEMPLATES_DIR
from app.core import data
from app.core.engine import handle_message, reset_session
from app.sms import outbox

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_BRAND: dict = {}


def brand_vars() -> dict:
    """Palette computed once per process."""
    if not _BRAND:
        _BRAND.update(brand.palette())
    return _BRAND


class SendIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    text: str = Field(min_length=1, max_length=480)
    offline: bool = False


class PhoneIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


def _sim_only(phone: str) -> None:
    if not phone.startswith(SIM_PREFIX):
        raise ApiError(400, "not_simulator", "The web simulator only uses simulator numbers (+97798000...).")


@router.get("/", response_class=HTMLResponse)
def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "chat.html", {"b": brand_vars()})


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin.html", {"b": brand_vars()})


@router.get("/api/chat/meta")
def chat_meta() -> dict:
    s = data.store()
    return {"is_sample": s.is_sample, "today": s.today, "provider": outbox.provider().name,
            "locations": [{"key": l["key"], "name_en": l["name_en"]} for l in locations.selectable()],
            "crops": s.crops()}


@router.post("/api/chat/new")
def chat_new() -> dict:
    return {"phone": new_sim_phone()}


@router.post("/api/chat/send")
def chat_send(body: SendIn) -> dict:
    _sim_only(body.phone)
    return handle_message("web", body.phone, body.text, offline=body.offline).to_dict()


@router.get("/api/chat/history")
def chat_history(phone: str) -> dict:
    _sim_only(phone)
    rows = db.q("SELECT id, ts, direction, channel, text, intent, segments, encoding, chars, trace_json FROM messages "
                "WHERE phone=? ORDER BY id DESC LIMIT 200", (phone,))
    return {"messages": list(reversed(rows))}


@router.post("/api/chat/reset")
def chat_reset(body: PhoneIn) -> dict:
    _sim_only(body.phone)
    reset_session(body.phone)
    return {"ok": True}

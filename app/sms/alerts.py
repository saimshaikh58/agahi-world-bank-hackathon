"""Daily alerts job: max 1 per farmer per day, only subscribed + onboarded, never in quiet hours."""
from __future__ import annotations

import json

from app import db, locations
from app.core.aliases import crop_name
from app.core.data import store
from app.core.templates import finish, fmt_date, money, signed, t
from app.core.sms import Part
from app.sms import compliance, outbox
from app.util import now
from app.weather import outlook

PRICE_MOVE = 0.10
RAIN_MM = 20.0
FC_MOVE = 10.0


def _alert_for(f: dict, ctx: dict, offline: bool) -> str | None:
    lang = f["lang"]
    s = store()
    crop = ctx.get("crop")
    if crop:
        p = s.price_today(crop)
        if p and p["prev"] and not p["stale"] and abs(p["price"] / p["prev"] - 1) >= PRICE_MOVE:
            pct = (p["price"] / p["prev"] - 1) * 100
            return t(lang, "al_price_up" if pct > 0 else "al_price_down", crop=crop_name(crop, lang), pct=signed(pct),
                     p=money(p["price"]), d=fmt_date(p["date"], lang))
    loc = f.get("location") or locations.AREA_KEY
    w = outlook.next7(loc, offline)
    if w["method"] in ("live", "cache") and w["tomorrow_rain"] >= RAIN_MM:
        return t(lang, "al_rain", mm=int(round(w["tomorrow_rain"])), loc=locations.short_name(locations.get(loc), lang))
    if crop:
        fc = s.forecast(crop, "d7")
        if fc and fc["status"] == "reliable" and fc["pct_change_p50"] is not None and abs(fc["pct_change_p50"]) >= FC_MOVE:
            return t(lang, "al_fc", crop=crop_name(crop, lang), pct=signed(fc["pct_change_p50"]),
                     lo=money(fc["p10"]), hi=money(fc["p90"]))
    return None


def run_alerts(respect_quiet: bool = True, offline: bool = False) -> dict:
    """Queue alerts. Returns counts."""
    if respect_quiet and compliance.quiet_now():
        return {"queued": 0, "skipped_quiet_hours": True, "checked": 0}
    day = now().date().isoformat()
    queued = checked = 0
    for f in db.q("SELECT * FROM farmers WHERE demo=0"):
        if not compliance.can_push(f) or db.q1("SELECT 1 AS x FROM alerts_log WHERE phone=? AND day=?", (f["phone"], day)):
            continue
        checked += 1
        sess = db.q1("SELECT ctx_json FROM sessions WHERE phone=?", (f["phone"],))
        ctx = json.loads(sess["ctx_json"]) if sess else {}
        text = _alert_for(f, ctx, offline)
        if not text:
            continue
        body, _ = finish([Part(text, 0, "alert", True)], f["lang"], store().is_sample)
        outbox.enqueue(f["phone"], body, "alert", idem=f"alert:{f['phone']}:{day}")
        db.x("INSERT OR IGNORE INTO alerts_log(phone,day,kind) VALUES(?,?,?)", (f["phone"], day, "alert"))
        queued += 1
    return {"queued": queued, "skipped_quiet_hours": False, "checked": checked}

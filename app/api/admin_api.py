"""Admin JSON API. Every route requires login; POST routes require the CSRF header. Phones are always masked."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import platform
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from importlib import metadata
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app import db, events, jobs, locations, scenarios, seed
from app.api import auth
from app.api.errors import ApiError
from app.config import MODELS_DIR, REPORTS_DIR, settings, twilio_ready
from app.core import aliases, data, replies
from app.core.aliases import CROP_NAMES, HORIZONS, crop_name
from app.core.engine import handle_message, reset_session
from app.core.sms import sms_stats
from app.forecast import predict
from app.forecast.prep import HORIZON_DAYS
from app.ingest.bundle import IngestError, ingest_path
from app.sms import alerts, compliance, outbox
from app.util import mask_phone, now, now_iso
from app.weather import climatology, outlook

router = APIRouter(prefix="/api/admin")
public = APIRouter()
RANGES = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
PAGE = 50
SIM_PREFIX = "+97798000"


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=480)


class TrainIn(BaseModel):
    mode: str = Field(default="fast", pattern="^(fast|full)$")


class ChatIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    text: str = Field(min_length=1, max_length=480)
    offline: bool = False


class PhoneIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class BroadcastIn(BaseModel):
    text: str = Field(min_length=1, max_length=480)
    crop: str | None = None
    location: str | None = None
    lang: str | None = None
    override_quiet: bool = False


class AliasIn(BaseModel):
    alias: str = Field(min_length=2, max_length=40)
    crop: str


class ScenarioIn(BaseModel):
    name: str | None = None


class AlertsIn(BaseModel):
    override_quiet: bool = False


# ---------------- auth ----------------
@public.post("/api/admin/login")
def login(body: LoginIn, request: Request) -> Response:
    ip = request.client.host if request.client else "?"
    if not auth.check_password(body.password, ip):
        raise ApiError(401, "bad_password", "Wrong password.")
    token = auth.make_token()
    resp = Response(json.dumps({"ok": True, "csrf": auth.csrf_for(token)}), media_type="application/json")
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").startswith("https")
    resp.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", secure=https, max_age=auth.SESSION_HOURS * 3600)
    return resp


@router.post("/logout")
def logout(_: str = Depends(auth.require_admin)) -> Response:
    resp = Response(json.dumps({"ok": True}), media_type="application/json")
    resp.delete_cookie(auth.COOKIE)
    return resp


@router.get("/me")
def me(token: str = Depends(auth.require_admin)) -> dict:
    return {"csrf": auth.csrf_for(token)}


# ---------------- status / overview ----------------
@router.get("/status")
def status(_: str = Depends(auth.require_admin)) -> dict:
    s = data.store()
    lw = db.q1("SELECT MAX(date) AS d FROM weather")
    return {"is_sample": s.is_sample, "demo_rows": seed.demo_rows(), "models_trained": s.run_id is not None,
            "data_version": s.data_version, "today": s.today, "latest_weather": lw["d"] if lw else None,
            "provider": outbox.provider().name, "simulated": outbox.provider().simulated,
            "env": "Phase 1: Web simulator" if outbox.provider().simulated else f"Live SMS: {outbox.provider().name}",
            "train_running": bool(jobs.running("train")), "serverless": settings.serverless,
            "now": now_iso(), "timezone": "Asia/Kathmandu"}


def _since(rng: str, offset: int = 0) -> tuple[str, str]:
    days = RANGES.get(rng, 7)
    end = now() - timedelta(days=days * offset)
    start = end - timedelta(days=days)
    return start.replace(microsecond=0).isoformat(), end.replace(microsecond=0).isoformat()


def _demo_clause(include_demo: bool) -> str:
    return "" if include_demo else " AND demo=0"


@router.get("/overview")
def overview(rng: str = Query("7d", alias="range"), include_demo: bool = True, _: str = Depends(auth.require_admin)) -> dict:
    s0, s1 = _since(rng)
    p0, p1 = _since(rng, 1)
    dc = _demo_clause(include_demo)
    inb = db.q(f"SELECT ts, lang, intent, crop, location, phone FROM messages WHERE direction='in' AND ts>=? AND ts<?{dc}", (s0, s1))
    out = db.q(f"SELECT ts, segments, latency_ms, encoding FROM messages WHERE direction='out' AND ts>=? AND ts<?{dc}", (s0, s1))
    prev = db.q1(f"SELECT COUNT(*) AS n FROM messages WHERE direction='in' AND ts>=? AND ts<?{dc}", (p0, p1))["n"]
    farmers_started = db.q(f"SELECT onboarding_state FROM farmers WHERE created_at>=? AND created_at<?{dc}", (s0, s1))
    lat = [m["latency_ms"] for m in out if m["latency_ms"] is not None]
    n_in = len(inb)
    kpis = {
        "messages": n_in, "messages_prev": prev,
        "messages_change_pct": round((n_in / prev - 1) * 100, 1) if prev else None,
        "unique_farmers": len({m["phone"] for m in inb}),
        "onboarding_started": len(farmers_started),
        "onboarding_completion": round(sum(f["onboarding_state"] == "DONE" for f in farmers_started) / len(farmers_started), 3)
        if farmers_started else None,
        "avg_segments": round(float(np.mean([m["segments"] or 1 for m in out])), 2) if out else None,
        "latency_p50": round(float(np.percentile(lat, 50)), 1) if lat else None,
        "latency_p95": round(float(np.percentile(lat, 95)), 1) if lat else None,
        "unknown_rate": round(sum(m["intent"] in ("UNKNOWN", "CLARIFY") for m in inb) / n_in, 3) if n_in else None,
        "sms_cost_npr": round(sum((m["segments"] or 1) for m in out) * settings.sms_cost, 1),
        "forecast_share": round(sum(m["intent"] == "FORECAST" for m in inb) / n_in, 3) if n_in else None,
    }
    days = sorted({m["ts"][:10] for m in inb})
    vol = {lg: [sum(1 for m in inb if m["ts"][:10] == d and m["lang"] == lg) for d in days] for lg in ("en", "rn", "ne")}
    heat = [[0] * 24 for _ in range(7)]
    for m in inb:
        dt = datetime.fromisoformat(m["ts"])
        heat[dt.weekday()][dt.hour] += 1
    lat_days = []
    for d in sorted({m["ts"][:10] for m in out}):
        v = [m["latency_ms"] for m in out if m["ts"][:10] == d and m["latency_ms"] is not None]
        if v:
            lat_days.append({"date": d, "p50": float(np.percentile(v, 50)), "p95": float(np.percentile(v, 95))})
    locs = {l["key"]: l["name_en"] for l in locations.all_locations()}
    by_loc = db.q(f"SELECT location, COUNT(*) AS n FROM farmers WHERE location IS NOT NULL{dc} GROUP BY location")
    return {
        "kpis": kpis, "volume": {"days": days, "series": vol},
        "intents": Counter(m["intent"] for m in inb).most_common(),
        "crops": Counter(m["crop"] for m in inb if m["crop"]).most_common(8),
        "locations": [[locs.get(r["location"], r["location"]), r["n"]] for r in by_loc],
        "heatmap": heat, "latency": lat_days, "languages": Counter(m["lang"] for m in inb).most_common(),
        "segments": Counter(int(m["segments"] or 1) for m in out).most_common(), "range": rng,
    }


# ---------------- conversations ----------------
def _farmer_out(f: dict) -> dict:
    return {"id": f["id"], "phone": mask_phone(f["phone"]), "lang": f["lang"], "location": f["location"],
            "onboarding_state": f["onboarding_state"], "subscribed": bool(f["subscribed"]), "last_seen": f["last_seen"],
            "demo": bool(f["demo"]), "created_at": f["created_at"]}


@router.get("/conversations")
def conversations(lang: str = "", intent: str = "", location: str = "", unknown: bool = False, page: int = 0,
                  _: str = Depends(auth.require_admin)) -> dict:
    where, params = ["1=1"], []
    if lang:
        where.append("f.lang=?")
        params.append(lang)
    if location:
        where.append("f.location=?")
        params.append(location)
    if intent:
        where.append("EXISTS (SELECT 1 FROM messages m2 WHERE m2.phone=f.phone AND m2.intent=?)")
        params.append(intent)
    if unknown:
        where.append("EXISTS (SELECT 1 FROM messages m3 WHERE m3.phone=f.phone AND m3.intent IN ('UNKNOWN','CLARIFY'))")
    rows = db.q(f"""SELECT f.*, (SELECT text FROM messages m WHERE m.phone=f.phone ORDER BY id DESC LIMIT 1) AS last_text,
                    (SELECT COUNT(*) FROM messages m WHERE m.phone=f.phone) AS n
                    FROM farmers f WHERE {' AND '.join(where)} ORDER BY f.last_seen DESC LIMIT ? OFFSET ?""",
                params + [PAGE, max(0, page) * PAGE])
    return {"items": [_farmer_out(r) | {"last_text": r["last_text"], "n": r["n"]} for r in rows], "page": page}


@router.get("/conversations/{fid}")
def conversation(fid: int, _: str = Depends(auth.require_admin)) -> dict:
    f = db.q1("SELECT * FROM farmers WHERE id=?", (fid,))
    if not f:
        raise ApiError(404, "not_found", "Farmer not found.")
    msgs = db.q("SELECT id, ts, direction, channel, text, lang, intent, confidence, crop, horizon, location, state, "
                "segments, encoding, chars, latency_ms, trace_json FROM messages WHERE phone=? ORDER BY id DESC LIMIT 200",
                (f["phone"],))
    for m in msgs:
        m["trace"] = json.loads(m.pop("trace_json")) if m.get("trace_json") else None
    return {"farmer": _farmer_out(f), "messages": list(reversed(msgs))}


@router.post("/conversations/{fid}/reply")
def operator_reply(fid: int, body: TextIn, _: str = Depends(auth.require_admin)) -> dict:
    f = db.q1("SELECT * FROM farmers WHERE id=?", (fid,))
    if not f:
        raise ApiError(404, "not_found", "Farmer not found.")
    oid = outbox.enqueue(f["phone"], body.text, "operator", demo=bool(f["demo"]))
    _flush_if_serverless()
    return {"ok": True, "outbox_id": oid, "segments": sms_stats(body.text)["segments"]}


# ---------------- market & forecasts ----------------
@router.get("/market")
def market(crop: str = "tomato", _: str = Depends(auth.require_admin)) -> dict:
    s = data.store()
    if crop not in s.crops():
        crop = s.crops()[0] if s.crops() else crop
    hist = db.q("SELECT date, avg_kg, min_kg, max_kg, carried_over, variant, origin, size FROM prices "
                "WHERE crop=? AND is_primary=1 ORDER BY date", (crop,))
    second = db.q("""SELECT p.date, p.avg_kg, p.variant FROM prices p WHERE p.crop=? AND p.is_primary=0 AND p.variant=
                     (SELECT variant FROM prices WHERE crop=? AND is_primary=0 GROUP BY variant ORDER BY COUNT(*) DESC LIMIT 1)
                     ORDER BY p.date""", (crop, crop))
    arr = db.q("SELECT date, arrivals_kg FROM daily_crop WHERE crop=? ORDER BY date", (crop,))
    start = hist[0]["date"] if hist else "2000-01-01"
    rain = db.q("SELECT date, rain FROM weather WHERE location=? AND date>=? ORDER BY date", (locations.AREA_KEY, start))
    fcs = []
    for h in HORIZONS:
        f = s.forecast(crop, h)
        if not f:
            continue
        target = (datetime.fromisoformat(f["origin_date"]) + timedelta(days=HORIZON_DAYS[h])).date().isoformat() \
            if f["origin_date"] else None
        bt = db.q1("SELECT skill, coverage, dir_acc, n_test FROM backtest_results WHERE run_id=? AND crop=? AND horizon=? "
                   "AND chosen=1", (s.run_id, crop, h)) or {}
        fcs.append(f | {"target_date": target, "backtest": bt})
    corr_path = REPORTS_DIR / "weather_market_corr.json"
    corr = json.loads(corr_path.read_text(encoding="utf-8")) if corr_path.exists() else {}
    real = [r for r in hist if not r["carried_over"]]
    first, last = (hist[0]["date"], hist[-1]["date"]) if hist else (None, None)
    span = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days + 1 if hist else 0
    meta = hist[-1] if hist else {}
    return {"crop": crop, "crop_name": crop_name(crop, "en"), "crops": [{"key": c, "name": crop_name(c, "en")} for c in s.crops()],
            "variant": meta.get("variant"), "history": [{"date": r["date"], "avg": r["avg_kg"], "min": r["min_kg"],
                                                         "max": r["max_kg"]} for r in hist],
            "variants": {"name": second[0]["variant"] if second else None,
                         "series": [{"date": r["date"], "avg": r["avg_kg"]} for r in second]},
            "forecasts": fcs, "arrivals": arr, "rain": rain,
            "corr": {"lags": corr.get("lags", []), "crop": corr.get("crops", {}).get(crop), "note": corr.get("note")},
            "latest": list(reversed(hist[-14:])),
            "health": {"first": first, "last": last, "days_with_price": len(real), "calendar_days": span,
                       "missing_days": span - len(hist), "carried_over_share": round(1 - len(real) / len(hist), 3) if hist else None}}


# ---------------- models ----------------
@router.get("/models")
def models(_: str = Depends(auth.require_admin)) -> dict:
    runs = db.q("SELECT id, started_at, finished_at, mode, data_version, summary_json FROM model_runs ORDER BY id DESC LIMIT 20")
    for r in runs:
        r["summary"] = json.loads(r.pop("summary_json") or "{}")
    rid = next((r["id"] for r in runs if r["finished_at"]), None)
    matrix = db.q("SELECT crop, horizon, model, status, skill, coverage, dir_acc, mae_rs, n_test FROM backtest_results "
                  "WHERE run_id=? AND chosen=1", (rid,)) if rid else []
    ie = db.q1("SELECT * FROM intent_eval WHERE run_id=?", (rid,)) if rid else None
    intent = None
    if ie:
        ev_path = REPORTS_DIR / "intent_eval.json"
        ev = json.loads(ev_path.read_text(encoding="utf-8")) if ev_path.exists() else {}
        intent = {"accuracy": ie["accuracy"], "by_lang": json.loads(ie["by_lang_json"]), "confusion": json.loads(ie["confusion_json"]),
                  "labels": json.loads(ie["labels_json"]), "n_test": ie["n_test"], "file_bytes": ev.get("file_bytes"),
                  "inference_ms": ev.get("inference_ms"), "chosen": ev.get("chosen"), "comparison": ev.get("comparison", {}),
                  "features": ev.get("features"), "casual_pipeline_accuracy": ev.get("casual_pipeline_accuracy"),
                  "casual_classifier_accuracy": ev.get("casual_classifier_accuracy"), "casual_n": ev.get("casual_n"),
                  "casual_by_lang": ev.get("casual_by_lang", {}), "casual_misses": ev.get("casual_misses", [])}
    wx = db.q("SELECT location, week, variable, mae_model, mae_clim, skill, n, kept FROM weather_backtest WHERE run_id=? "
              "ORDER BY location, variable, week", (rid,)) if rid else []
    fp = predict.footprint()
    wfiles = list((MODELS_DIR / "weather").glob("*.joblib"))
    ifiles = [MODELS_DIR / "intent" / n for n in ("intent_lite.json", "intent_lite.npz")]
    fp["weather_bytes"] = sum(p.stat().st_size for p in wfiles)
    fp["intent_bytes"] = sum(p.stat().st_size for p in ifiles if p.exists())
    fp["total_bytes"] = fp["price_bytes"] + fp["weather_bytes"] + fp["intent_bytes"]
    return {"run": runs[0] if runs else None, "runs": runs, "run_id": rid, "matrix": matrix, "intent": intent,
            "weather": wx, "footprint": fp, "horizons": HORIZONS}


def _calibration(pred: np.ndarray, actual: np.ndarray) -> list[dict]:
    """Nominal vs actual coverage, calibrating each point only on earlier residuals (min 30)."""
    out = []
    resid = actual - pred
    for nominal in (0.5, 0.6, 0.7, 0.8, 0.9):
        lo_q, hi_q = (1 - nominal) / 2, 1 - (1 - nominal) / 2
        hits = n = 0
        for i in range(30, len(resid)):
            past = resid[:i]
            lo, hi = np.quantile(past, [lo_q, hi_q])
            hits += int(lo <= resid[i] <= hi)
            n += 1
        out.append({"nominal": nominal, "actual": hits / n if n else None})
    return out


@router.get("/models/cell")
def model_cell(crop: str, horizon: str, _: str = Depends(auth.require_admin)) -> dict:
    rid = data.store().run_id
    if rid is None:
        raise ApiError(404, "not_trained", "Models are not trained yet.")
    preds = db.q("SELECT origin_date, price0, actual, pred, lo, hi FROM backtest_preds WHERE run_id=? AND crop=? AND horizon=? "
                 "ORDER BY origin_date", (rid, crop, horizon))
    by_model = db.q("SELECT model, mae_log, mae_rs, mape, dir_acc, skill, pinball, coverage, width, n_test, chosen, status "
                    "FROM backtest_results WHERE run_id=? AND crop=? AND horizon=?", (rid, crop, horizon))
    by_h = db.q("SELECT horizon, model, mae_rs, chosen FROM backtest_results WHERE run_id=? AND crop=?", (rid, crop))
    p = np.array([r["pred"] for r in preds]) if preds else np.array([])
    a = np.array([r["actual"] for r in preds]) if preds else np.array([])
    resid = (a - p) if len(p) else np.array([])
    hist, edges = np.histogram(resid, bins=30) if len(resid) else ([], [])
    meta_path = MODELS_DIR / "price" / f"{crop}_{horizon}.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    ledger = db.q("SELECT origin_date, target_date, p10, p50, p90, price0, realised, status FROM forecast_ledger "
                  "WHERE crop=? AND horizon=? ORDER BY origin_date", (crop, horizon))
    return {"preds": [{"date": r["origin_date"], "actual": r["price0"] * np.exp(r["actual"]),
                       "pred": r["price0"] * np.exp(r["pred"]),
                       "lo": r["price0"] * np.exp(r["lo"]) if r["lo"] is not None else None,
                       "hi": r["price0"] * np.exp(r["hi"]) if r["hi"] is not None else None} for r in preds],
            "by_model": by_model, "by_horizon": by_h, "calibration": _calibration(p, a) if len(p) > 40 else [],
            "residuals": {"counts": [int(x) for x in hist], "edges": [float(x) for x in edges]},
            "importance": meta.get("importance", []), "meta": {k: meta.get(k) for k in ("chosen", "status", "trained_at",
                                                                                          "file_bytes", "inference_ms", "best_baseline", "n_rows")},
            "ledger": ledger}


@router.get("/reports/model_card.md")
def model_card(_: str = Depends(auth.require_admin)) -> PlainTextResponse:
    p = REPORTS_DIR / "model_card.md"
    if not p.exists():
        raise ApiError(404, "not_found", "Model card not generated yet. Train first.")
    return PlainTextResponse(p.read_text(encoding="utf-8"), media_type="text/markdown",
                             headers={"Content-Disposition": "attachment; filename=model_card.md"})


# ---------------- weather ----------------
@router.get("/weather")
def weather(location: str = "", _: str = Depends(auth.require_admin)) -> dict:
    loc = location or (locations.selectable()[0]["key"] if locations.selectable() else locations.AREA_KEY)
    if not locations.get(loc):
        raise ApiError(404, "not_found", "Unknown location.")
    n7 = outlook.next7(loc)
    w24 = outlook.weeks24(loc)
    m13 = outlook.months13(loc)
    recent = db.q("SELECT date, rain, tmax, tmin FROM weather WHERE location=? ORDER BY date DESC LIMIT 60", (loc,))
    recent = list(reversed(recent))
    for r in recent:
        c = climatology.day(loc, datetime.fromisoformat(r["date"]).timetuple().tm_yday) or {}
        r["rain_clim"] = c.get("rain_mean")
        r["tmax_clim"] = c.get("tmax_mean")
    return {"location": loc, "locations": [{"key": l["key"], "name": l["name_en"], "has_coords": l["lat"] is not None}
                                           for l in locations.all_locations()],
            "next7": n7, "weeks": w24, "months": m13, "recent": recent}


# ---------------- data & training ----------------
@router.get("/data")
def data_page(_: str = Depends(auth.require_admin)) -> dict:
    versions = db.q("SELECT id, created_at, checksum, is_sample, active FROM dataset_versions ORDER BY id DESC")
    act = db.q1("SELECT report_json FROM dataset_versions WHERE active=1")
    last_job = db.q1("SELECT * FROM jobs WHERE kind='train' ORDER BY id DESC LIMIT 1")
    return {"versions": versions, "report": json.loads(act["report_json"]) if act else None,
            "locations": locations.all_locations(), "last_job": last_job, "default_mode": settings.train_mode}


@router.get("/syscheck")
def syscheck(_: str = Depends(auth.require_admin)) -> dict:
    checks = [{"name": "Python", "ok": sys.version_info >= (3, 10), "detail": platform.python_version()}]
    for pkg in ("fastapi", "uvicorn", "pandas", "numpy", "joblib", "rapidfuzz", "httpx", "Pillow"):
        try:
            checks.append({"name": pkg, "ok": True, "detail": metadata.version(pkg)})
        except metadata.PackageNotFoundError:
            checks.append({"name": pkg, "ok": False, "detail": "not installed"})
    try:
        db.q1("SELECT 1 AS x")
        checks.append({"name": "Database", "ok": True, "detail": str(settings.db_path.name)})
    except Exception as e:  # report, never crash
        checks.append({"name": "Database", "ok": False, "detail": str(e)})
    s = data.store()
    checks.append({"name": "Dataset loaded", "ok": s.today is not None,
                   "detail": f"v{s.data_version}, prices to {s.today}" + (" (SAMPLE)" if s.is_sample else "")})
    n_models = len(list((MODELS_DIR / "price").glob("*.joblib")))
    checks.append({"name": "Models present", "ok": n_models > 0, "detail": f"{n_models} price artifacts"})
    from app.weather import live
    live.reset_backoff()
    loc = locations.get("kathmandu_valley") or {"lat": 27.7, "lon": 85.32}
    days, src = live.forecast7("__syscheck__", loc["lat"], loc["lon"])
    checks.append({"name": "Open-Meteo reachable", "ok": src == "live",
                   "detail": "live" if src == "live" else "unreachable: weather falls back to climatology"})
    db.x("DELETE FROM weather_cache WHERE location='__syscheck__'")
    p = outbox.provider()
    if p.name == "twilio":
        ready = twilio_ready(settings)
        missing = [k for k, v in ready.items() if not v]
        checks.append({"name": "Provider", "ok": all(ready[k] for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER")),
                       "detail": "twilio, settings present: " + ", ".join(k for k, v in ready.items() if v)
                       + ("; missing: " + ", ".join(missing) if missing else "")})
    else:
        checks.append({"name": "Provider", "ok": True, "detail": p.name + (" (simulated, no real SMS)" if p.simulated else "")})
    from app.brand import LOGO
    checks.append({"name": "Logo found", "ok": LOGO.exists(), "detail": "app/static/brand/logo.png" if LOGO.exists() else "text wordmark used"})
    free = shutil.disk_usage(settings.db_path.parent).free
    checks.append({"name": "Disk space", "ok": free > 500e6, "detail": f"{free / 1e9:.1f} GB free"})
    return {"checks": checks}


@router.post("/upload")
async def upload(file: UploadFile = File(...), _: str = Depends(auth.require_admin)) -> dict:
    if not (file.filename or "").lower().endswith(".zip"):
        raise ApiError(400, "bad_file", "Please upload a .zip file.")
    limit = settings.max_upload_mb * 1024 * 1024
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bundle.zip"
        size = 0
        with open(path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ApiError(413, "too_large", f"ZIP is larger than {settings.max_upload_mb} MB.")
                f.write(chunk)
        try:
            report = await asyncio.to_thread(ingest_path, path, False)
        except IngestError as e:
            raise ApiError(400, "invalid_bundle", str(e))
    data.invalidate()
    return {"ok": True, "version_id": report.get("version_id"), "report": report}


@router.post("/train")
def train(body: TrainIn, _: str = Depends(auth.require_admin)) -> dict:
    if settings.serverless:
        raise ApiError(400, "training_off", "Training is turned off on this host. Train locally, run "
                                            "scripts/prepare_deploy.py, then redeploy.")
    try:
        from app.training import run_training  # training code needs scikit-learn (requirements-train.txt)
    except ImportError:
        raise ApiError(400, "training_off", "Training packages are missing. Run: pip install -r requirements-train.txt")
    try:
        jid = jobs.start("train", run_training, {"mode": body.mode})
    except jobs.JobBusy as e:
        raise ApiError(400 if settings.serverless else 409, "training_off" if settings.serverless else "busy", str(e))
    return {"job_id": jid}


@router.get("/jobs/{job_id}")
def job(job_id: int, _: str = Depends(auth.require_admin)) -> dict:
    j = jobs.get(job_id)
    if not j:
        raise ApiError(404, "not_found", "Job not found.")
    return j


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: int, _: str = Depends(auth.require_admin)) -> StreamingResponse:
    async def gen():
        while True:
            j = await asyncio.to_thread(jobs.get, job_id)
            if not j:
                break
            yield f"event: job\ndata: {json.dumps(j)}\n\n"
            if j["status"] not in ("queued", "running"):
                break
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int, _: str = Depends(auth.require_admin)) -> dict:
    return {"ok": jobs.cancel(job_id)}


# ---------------- farmers ----------------
@router.get("/farmers")
def farmers(location: str = "", state: str = "", page: int = 0, _: str = Depends(auth.require_admin)) -> dict:
    where, params = ["1=1"], []
    if location:
        where.append("location=?")
        params.append(location)
    if state:
        where.append("onboarding_state=?")
        params.append(state)
    rows = db.q(f"SELECT * FROM farmers WHERE {' AND '.join(where)} ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                params + [PAGE, max(0, page) * PAGE])
    total = db.q1(f"SELECT COUNT(*) AS n FROM farmers WHERE {' AND '.join(where)}", params)["n"]
    return {"items": [_farmer_out(r) for r in rows], "page": page, "total": total}


@router.get("/farmers.csv")
def farmers_csv(_: str = Depends(auth.require_admin)) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "phone_masked", "lang", "location", "onboarding_state", "subscribed", "created_at", "last_seen", "demo"])
    for f in db.q("SELECT * FROM farmers ORDER BY id"):
        w.writerow([f["id"], mask_phone(f["phone"]), f["lang"], f["location"], f["onboarding_state"], f["subscribed"],
                    f["created_at"], f["last_seen"], f["demo"]])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=farmers.csv"})


# ---------------- alerts & broadcast ----------------
def _audience(b: BroadcastIn) -> list[dict]:
    where, params = ["subscribed=1", "onboarding_state='DONE'", "consent_at IS NOT NULL"], []
    if b.location:
        where.append("location=?")
        params.append(b.location)
    if b.lang:
        where.append("lang=?")
        params.append(b.lang)
    if b.crop:
        where.append("phone IN (SELECT phone FROM messages WHERE crop=?)")
        params.append(b.crop)
    return db.q(f"SELECT * FROM farmers WHERE {' AND '.join(where)}", params)


@router.post("/broadcast/preview")
def broadcast_preview(body: BroadcastIn, _: str = Depends(auth.require_admin)) -> dict:
    st = sms_stats(body.text)
    n = len(_audience(body))
    return {"recipients": n, **st, "cost_npr": round(n * st["segments"] * settings.sms_cost, 2),
            "quiet_hours": compliance.quiet_now(), "over_budget": st["segments"] > 2}


@router.post("/broadcast/send")
def broadcast_send(body: BroadcastIn, _: str = Depends(auth.require_admin)) -> dict:
    if compliance.quiet_now() and not body.override_quiet:
        raise ApiError(400, "quiet_hours", "Quiet hours (21:00-06:00 Kathmandu). Tick 'override' only for testing.")
    aud = _audience(body)
    bid = db.x("INSERT INTO broadcasts(ts,text,audience_json,recipients) VALUES(?,?,?,?)",
               (now_iso(), body.text, json.dumps(body.model_dump(exclude={"text"})), len(aud)))
    for f in aud:
        outbox.enqueue(f["phone"], body.text, "broadcast", idem=f"bc:{bid}:{f['phone']}", demo=bool(f["demo"]))
    _flush_if_serverless()
    return {"queued": len(aud), "broadcast_id": bid}


@router.get("/broadcasts")
def broadcasts(_: str = Depends(auth.require_admin)) -> dict:
    return {"items": db.q("SELECT * FROM broadcasts ORDER BY id DESC LIMIT 50")}


@router.post("/alerts/run")
def alerts_run(body: AlertsIn, _: str = Depends(auth.require_admin)) -> dict:
    out = alerts.run_alerts(respect_quiet=not body.override_quiet)
    _flush_if_serverless()
    return out


def _flush_if_serverless() -> None:
    """No background worker on serverless hosts: send queued messages now, inside the request."""
    if settings.serverless:
        outbox.process_once(limit=100)


# ---------------- SMS operations ----------------
@router.get("/sms")
def sms_ops(_: str = Depends(auth.require_admin)) -> dict:
    ob = db.q("SELECT id, created_at, phone, text, kind, status, attempts, encoding, segments, cost, error, provider "
              "FROM outbox ORDER BY id DESC LIMIT 100")
    for m in ob:
        m["phone"] = mask_phone(m["phone"])
    wh = db.q("SELECT id, ts, kind, ok, note FROM webhook_log ORDER BY id DESC LIMIT 50")
    return {"funnel": outbox.funnel(), "outbox": ob, "webhooks": wh, "optouts": compliance.optout_count(),
            "provider": outbox.provider().name, "simulated": outbox.provider().simulated,
            "quiet_hours": compliance.quiet_now(), "cost_per_segment": settings.sms_cost}


# ---------------- quality ----------------
@router.get("/quality")
def quality(_: str = Depends(auth.require_admin)) -> dict:
    unk = db.q("SELECT id, ts, text, lang, demo FROM messages WHERE direction='in' AND intent IN ('UNKNOWN','CLARIFY') "
               "AND text NOT GLOB '[0-9]*' ORDER BY id DESC LIMIT 100")
    tpl = []
    loc = (locations.selectable() or [{"key": locations.AREA_KEY}])[0]["key"]
    s = data.store()
    crop = s.crops()[0] if s.crops() else "tomato"
    for lang in ("en", "rn", "ne"):
        for name, r in (("welcome", replies.welcome(lang)), ("location", replies.location_prompt(lang)),
                        ("main", replies.main_menu(lang)), ("price", replies.price(lang, crop, loc, True, s.is_sample)),
                        ("forecast d14", replies.forecast(lang, crop, "d14", s.is_sample)),
                        ("weather 7d", replies.weather7(lang, loc, True, s.is_sample))):
            tpl.append({"name": name, "lang": lang, "text": r.text, **sms_stats(r.text)})
    return {"unknown": unk, "templates": tpl, "crops": [{"key": k, "name": v[0]} for k, v in CROP_NAMES.items()]}


@router.post("/quality/alias")
def save_alias(body: AliasIn, _: str = Depends(auth.require_admin)) -> dict:
    if body.crop not in CROP_NAMES:
        raise ApiError(400, "bad_crop", "Unknown crop.")
    aliases.save_override(body.alias, body.crop)
    return {"ok": True}


# ---------------- test console ----------------
@router.post("/test/chat")
def test_chat(body: ChatIn, _: str = Depends(auth.require_admin)) -> dict:
    if not body.phone.startswith(SIM_PREFIX):
        raise ApiError(400, "not_simulator", "Test Console only uses simulator numbers.")
    return handle_message("web", body.phone, body.text, offline=body.offline).to_dict()


@router.post("/test/new-farmer")
def test_new(_: str = Depends(auth.require_admin)) -> dict:
    return {"phone": new_sim_phone()}


@router.post("/test/reset")
def test_reset(body: PhoneIn, _: str = Depends(auth.require_admin)) -> dict:
    if not body.phone.startswith(SIM_PREFIX):
        raise ApiError(400, "not_simulator", "Only simulator numbers can be reset.")
    reset_session(body.phone)
    return {"ok": True}


@router.get("/test/forecast")
def test_forecast(crop: str, horizon: str, _: str = Depends(auth.require_admin)) -> dict:
    s = data.store()
    if horizon not in HORIZONS or crop not in s.crops():
        raise ApiError(400, "bad_input", "Unknown crop or horizon.")
    f = s.forecast(crop, horizon) or {}
    base = db.q("SELECT model, mae_rs, skill, dir_acc, coverage, n_test, chosen, status FROM backtest_results "
                "WHERE run_id=? AND crop=? AND horizon=?", (s.run_id, crop, horizon)) if s.run_id else []
    sms = {}
    for lang in ("en", "rn", "ne"):
        r = replies.forecast(lang, crop, horizon, s.is_sample)
        sms[lang] = {"text": r.text, **sms_stats(r.text)}
    return {"crop": crop, "horizon": horizon, "p10": f.get("p10"), "p50": f.get("p50"), "p90": f.get("p90"),
            "price0": f.get("price0"), "pct": f.get("pct_change_p50"), "status": f.get("status", "not trained"),
            "model": f.get("model_name"), "baselines": base, "sms": sms}


@router.get("/test/weather")
def test_weather(location: str, horizon: str = "d7", _: str = Depends(auth.require_admin)) -> dict:
    if not locations.get(location):
        raise ApiError(400, "bad_input", "Unknown location.")
    s = data.store()
    sms = {}
    for lang in ("en", "rn", "ne"):
        if horizon == "w24":
            r = replies.weeks24(lang, location, s.is_sample)
        elif horizon == "m13":
            r = replies.months13(lang, location, s.is_sample)
        else:
            r = replies.weather7(lang, location, False, s.is_sample)
        sms[lang] = {"text": r.text, **sms_stats(r.text)}
    values = outlook.weeks24(location) if horizon == "w24" else outlook.months13(location) if horizon == "m13" \
        else outlook.next7(location)
    return {"values": values, "method": values.get("method"), "sms": sms}


@router.get("/test/scenarios")
def test_scenarios(_: str = Depends(auth.require_admin)) -> dict:
    return {"scenarios": [{"name": n, "steps": [s[0] for s in steps]} for n, steps in scenarios.SCENARIOS]}


@router.post("/test/scenarios/run")
def test_scenarios_run(body: ScenarioIn, _: str = Depends(auth.require_admin)) -> dict:
    return scenarios.run(body.name)


@router.get("/test/template-check")
def test_template_check(_: str = Depends(auth.require_admin)) -> dict:
    return scenarios.template_check()


@router.post("/demo/purge")
def demo_purge(_: str = Depends(auth.require_admin)) -> dict:
    return {"deleted": seed.purge_demo()}


@router.get("/events")
async def admin_events(_: str = Depends(auth.require_admin)) -> StreamingResponse:
    return sse_response()


def sse_response() -> StreamingResponse:
    """Live message events with a 15 s keep-alive."""
    async def gen():
        q = events.subscribe()
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            events.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream")


def new_sim_phone() -> str:
    """A fresh simulator number +97798000xxxxx (counter kept in meta so numbers are never reused)."""
    n = int(db.get_meta("sim_counter", 0)) + 1
    db.set_meta("sim_counter", n)
    return f"{SIM_PREFIX}{n:05d}"

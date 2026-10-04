# API contract: agahi_hackathon

Written before the code. The front-end JavaScript calls only the routes listed here.
All JSON. Errors always use one shape:

```json
{"error": {"code": "not_found", "message": "Plain English explanation"}}
```

Status codes: 400 bad input, 401 not logged in, 403 CSRF or signature failure, 404 not found,
409 conflict (e.g. a training job already running), 413 upload too large, 429 rate limited, 500 internal.

Auth for `/api/admin/*`: HttpOnly SameSite=Lax cookie `agahi_admin` set by login. Every state-changing
admin request (POST) must send header `X-CSRF-Token` equal to the token returned by login or `/api/admin/me`.
Phone numbers are always masked in admin responses (`+977-98****1234`); farmers are referenced by integer `id`.

## Public

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| GET | `/` | none | | Chat simulator HTML |
| GET | `/admin` | none (login screen if no cookie) | | Dashboard HTML |
| GET | `/health` | none | | `{"status":"ok","db":true,"dataset":true,"models":true,"version":"1.0"}` |
| GET | `/api/chat/meta` | none | | `{"is_sample":bool,"today":"YYYY-MM-DD","locations":[{key,name_en}],"provider":"mock"}` |
| POST | `/api/chat/new` | none | `{}` | `{"phone":"+9779800000123"}` (fresh simulator number) |
| POST | `/api/chat/send` | none | `{"phone":str,"text":str(1..480),"offline":bool}` | `Reply` (below) |
| GET | `/api/chat/history?phone=` | none | | `{"messages":[{direction,text,ts,segments,encoding,chars}]}` (simulator numbers only) |
| POST | `/api/chat/reset` | none | `{"phone":str}` | `{"ok":true}` (simulator numbers only) |

`Reply` JSON:
```json
{"text":"...","lang":"rn","intent":"PRICE","intent_confidence":0.93,"state_before":"MAIN","state_after":"AFTER_PRICE",
 "crop":"tomato","horizon":null,"location":"dhading_besi","segments":1,"encoding":"GSM7","chars":112,
 "latency_ms":4.1,"trace":{"probs":{},"slots":{},"sources":[],"model":null,"status":null,"dropped_parts":[]}}
```

## SMS (phase 2 ready)

| Method | Path | Auth | Request | Response |
|---|---|---|---|---|
| POST | `/api/sms/inbound` | provider signature (`X-Twilio-Signature` for twilio; `X-Agahi-Signature` HMAC-SHA256 hex of the raw body with `SMS_WEBHOOK_SECRET` for mock and android_gateway). Off when `SMS_VERIFY_SIGNATURE=false`. | Twilio: form `From, To, Body, MessageSid`. Others: JSON | Twilio: TwiML `text/xml` `<Response><Message action=".../api/sms/status?oid=N">text</Message></Response>`, empty `<Response/>` for duplicates and silent cases, 403 with empty `<Response/>` on a bad signature. Others: `{"ok":true,"queued":int}` |
| POST | `/api/sms/status?oid=` | same | Twilio: form `MessageSid, MessageStatus`. Others: provider receipt | Twilio: empty TwiML. Others: `{"ok":true}`. `oid` (optional) is our outbox id for TwiML replies. |
| POST | `/api/jobs/alerts` | `Authorization: Bearer <ALERTS_TOKEN>`, or admin session + CSRF | `{}` | `{"queued":int,"skipped_quiet_hours":bool,"checked":int}` |

Signature URL: `PUBLIC_BASE_URL` + path + query; if `PUBLIC_BASE_URL` is empty, `X-Forwarded-Proto`://`X-Forwarded-Host` + path + query.

## Admin

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/admin/login` | `{"password":str}` | `{"ok":true,"csrf":str}` sets cookie; 401 bad password; 429 after 5 failures/5 min |
| POST | `/api/admin/logout` | | `{"ok":true}` |
| GET | `/api/admin/me` | | `{"csrf":str}` |
| GET | `/api/admin/status` | | `{"is_sample","demo_rows","models_trained","data_version","today","latest_weather","provider","simulated","env","train_running","serverless","now","timezone"}` |
| GET | `/api/admin/overview?range=24h|7d|30d|90d` | | `{"kpis":{...},"volume":[...],"intents":[...],"crops":[...],"locations":[...],"heatmap":[[...]],"latency":[...],"languages":[...],"segments":[...]}` |
| GET | `/api/admin/conversations?lang=&intent=&location=&unknown=&page=` | | `{"items":[{id,phone,lang,location,last_text,last_ts,n}],"page":int}` |
| GET | `/api/admin/conversations/{id}` | | `{"farmer":{...},"messages":[{...,trace}]}` |
| POST | `/api/admin/conversations/{id}/reply` | `{"text":str}` | `{"ok":true,"outbox_id":int,"segments":int}` |
| GET | `/api/admin/market?crop=` | | `{"crop","variant","history":[...],"forecasts":[...],"arrivals":[...],"rain":[...],"variants":[...],"corr":{...},"latest":[...],"health":{...}}` |
| GET | `/api/admin/models` | | `{"run":{...},"runs":[...],"matrix":[...],"footprint":{...},"intent":{accuracy,by_lang,confusion,labels,n_test,file_bytes,inference_ms,chosen,comparison,features,casual_pipeline_accuracy,casual_classifier_accuracy,casual_n,casual_by_lang,casual_misses},"weather":[...]}` |
| GET | `/api/admin/models/cell?crop=&horizon=` | | `{"preds":[...],"by_model":[...],"by_horizon":[...],"calibration":[...],"residuals":{...},"importance":[...],"ledger":[...]}` |
| GET | `/api/admin/weather?location=` | | `{"location","days":[...],"weeks":[...],"months":[...],"anomaly":{...},"method":str}` |
| GET | `/api/admin/data` | | `{"versions":[...],"report":{...},"locations":[...]}` |
| GET | `/api/admin/syscheck` | | `{"checks":[{"name","ok","detail"}]}` including a `Provider` line (provider name and which Twilio settings are present, never their values) |
| POST | `/api/admin/upload` | multipart `file` (.zip, max `MAX_UPLOAD_MB`) | `{"ok":true,"version_id":int,"report":{...}}` |
| POST | `/api/admin/train` | `{"mode":"fast"|"full"}` | `{"job_id":int}`; 409 if one is running; 400 `training_off` on serverless hosts or when training packages are missing |
| GET | `/api/admin/jobs/{id}` | | `{"id","kind","status","progress","log","error","started_at","finished_at"}` |
| GET | `/api/admin/jobs/{id}/stream` | | SSE, event `job` with the job JSON every second until finished |
| POST | `/api/admin/jobs/{id}/cancel` | | `{"ok":true}` |
| GET | `/api/admin/farmers?location=&state=&page=` | | `{"items":[{id,phone,lang,location,onboarding_state,subscribed,last_seen,demo}]}` |
| GET | `/api/admin/farmers.csv` | | masked CSV |
| POST | `/api/admin/broadcast/preview` | `{"text","crop","location","lang"}` | `{"recipients":int,"segments","encoding","chars","cost_npr","quiet_hours":bool}` |
| POST | `/api/admin/broadcast/send` | same | `{"queued":int}` |
| GET | `/api/admin/sms` | | `{"funnel":{...},"outbox":[...],"webhooks":[...],"optouts":int,"provider":str,"simulated":bool}` |
| GET | `/api/admin/quality` | | `{"unknown":[{id,text,lang,ts}],"templates":[{name,lang,text,segments,encoding,chars}]}` |
| POST | `/api/admin/quality/alias` | `{"alias":str,"crop":str}` | `{"ok":true}` |
| POST | `/api/admin/test/chat` | `{"phone","text","offline"}` | `Reply` |
| POST | `/api/admin/test/new-farmer` | | `{"phone"}` |
| POST | `/api/admin/test/reset` | `{"phone"}` | `{"ok":true}` |
| GET | `/api/admin/test/forecast?crop=&horizon=` | | `{"p10","p50","p90","status","model","baselines":[...],"metrics":{...},"sms":{"en":{text,segments,encoding,chars},"rn":...,"ne":...}}` |
| GET | `/api/admin/test/weather?location=&horizon=d7|w24|m13` | | `{"values":[...],"method","status","sms":{...}}` |
| GET | `/api/admin/test/scenarios` | | `{"scenarios":[{"name","steps"}]}` |
| POST | `/api/admin/test/scenarios/run` | `{"name":str|null}` | `{"results":[{"name","passed","detail","transcript"}],"passed":int,"total":int}` |
| GET | `/api/admin/test/template-check` | | `{"total":int,"over":int,"max_segments":int,"failures":[...]}` |
| POST | `/api/admin/demo/purge` | | `{"deleted":int}` |
| GET | `/api/admin/events` | | SSE, event `message` with `{phone,direction,text,intent,lang,ts}` |
| GET | `/api/admin/reports/model_card.md` | | text/markdown download |

Login sets the cookie with `Secure` when the request came over https (directly or via `X-Forwarded-Proto`).

## SSE events
On serverless hosts (`serverless: true` in status) and whenever an event stream fails, the dashboard polls the same JSON routes every 5 seconds instead.

- `message`: every inbound/outbound message logged by the engine or outbox.
- `job`: job status snapshot.

## Cross-module function signatures

```
app.core.sms.sms_stats(text: str) -> dict(encoding, chars, segments, units)
app.core.sms.fit_parts(parts: list[Part], max_segments: int = 2) -> tuple[str, list[str]]
app.core.engine.handle_message(channel: str, phone: str, text: str, provider_msg_id: str|None = None, offline: bool = False, demo: bool = False, ts: str|None = None) -> Reply
app.core.nlu.parse(text: str, last_crop: str|None = None, last: dict|None = None) -> NluResult   (last = {"intent","crop","horizon"})
app.core.nlu.spell_correct(s: str) -> tuple[str, list[tuple[str, str]]]
app.core.nlu.find_when(s: str) -> str|None
app.core.nlu.followup(s: str, slots: dict, last: dict) -> tuple[str, dict, str]|None
app.core.sms.menu_part(options: list[tuple[str,str]], priority=5, name="menu", required=False) -> Part
app.core.templates.change_word(lang, pct, keys: tuple[str,str,str], band) -> str
app.core.intent_lite.export(pipeline, kind, json_path, npz_path) ; load(json_path, npz_path) -> IntentLite|None
app.sms.twilio.signature(token, url, params) -> str ; twiml(text|None, action_url|None) -> str
app.sms.inbound.handle_inbound(raw, headers, url, data) -> InboundResult(queued, inline_text, outbox_id)
app.sms.inbound.handle_status(raw, headers, url, data, outbox_id=None) -> int
app.sms.outbox.record_inline(phone, text, inbound_id) -> int ; apply_status(provider_msg_id, status, outbox_id=None) -> bool
app.bootstrap.ensure_ready() -> None
app.core.data.store() -> DataStore   (.price_today(crop), .forecast(crop,h), .arrivals(crop), .crops(), .today)
app.core.advisor.advise(crop: str, qty: float|None, location: str) -> Advice
app.weather.outlook.next7(location: str, offline: bool) -> dict ; weeks24(location) -> dict ; months13(location) -> dict
app.forecast.features.build_features(df: DataFrame) -> DataFrame
app.forecast.backtest.walk_forward(X, y, dates, h, mode) -> dict
app.forecast.registry.train_all(mode: str, progress: Callable[[float,str],None], cancelled: Callable[[],bool]) -> int(run_id)
app.ingest.bundle.ingest_zip(path: Path, is_sample: bool = False) -> dict(report)
app.sms.outbox.enqueue(phone: str, text: str, kind: str, idem: str|None) -> int
app.jobs.start(kind: str, fn, params) -> int
```

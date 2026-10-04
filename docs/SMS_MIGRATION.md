# Real SMS

The chatbot, outbox, webhooks, receipts, retries, opt-out, quiet hours and rate limits are built in. The simulator (`SMS_PROVIDER=mock`) is the default. Real SMS needs a provider, an https address and a few settings. The README section "Deploy and connect" has the click-by-click version; this page is the reference.

## 1. Pick a provider
| | Twilio (supported, tested with mocked HTTP) | Android gateway phone (free path) |
|---|---|---|
| What | Cloud SMS API | An Android phone with a local SIM running an SMS gateway app (format of the open-source "SMS Gateway for Android") |
| Cost | Twilio credit per segment; prices depend on the country | Local SIM rates |
| Number | Twilio number | A local Nepali number farmers already trust |
| Settings | `SMS_PROVIDER=twilio`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `PUBLIC_BASE_URL` | `SMS_PROVIDER=android_gateway`, `ANDROID_GATEWAY_URL`, `ANDROID_GATEWAY_TOKEN=user:pass`, `SMS_WEBHOOK_SECRET` |

## 2. How Twilio is wired
- Inbound: Twilio posts form fields `From`, `To`, `Body`, `MessageSid` to `POST /api/sms/inbound`.
- The app checks `X-Twilio-Signature` (HMAC-SHA1 of the public URL plus the sorted form fields, base64, constant-time compare). The URL is `PUBLIC_BASE_URL` + path; if `PUBLIC_BASE_URL` is empty it is rebuilt from `X-Forwarded-Proto` and `X-Forwarded-Host`. `SMS_VERIFY_SIGNATURE=false` turns the check off (testing only).
- The reply goes back in the same HTTP response as TwiML (`text/xml`, text XML-escaped, line breaks kept). Duplicates (same `MessageSid`) and silent cases get an empty `<Response/>`.
- Each TwiML reply is also written to the outbox as `sent`, with an `action` URL so Twilio reports delivery to `/api/sms/status`.
- Alerts, broadcasts and operator replies use the Twilio Messages REST API (Basic auth, `From` = `TWILIO_PHONE_NUMBER`, `StatusCallback` = `<PUBLIC_BASE_URL>/api/sms/status`). Failures are retried with backoff, then marked failed after 3 tries.
- Status callback: `POST /api/sms/status` reads `MessageSid` and `MessageStatus` and updates the outbox.
- Numbers that start with `+` are kept as they are (any country). Local numbers without `+` get `+977`.
- Twilio handles `STOP`, `START` and `HELP` itself on most numbers and sends its own reply; the app still records the opt-out and blocks alerts.

## 3. Test
1. Free first: dashboard, Test Console, Chat test. Nothing is sent.
2. Send `hello` from a verified phone: you should get the welcome.
3. Dashboard, SMS operations: the webhook log shows the inbound, the outbox shows the reply as `sent` then `delivered`. The page shows the provider name; the SIMULATED badge appears only for mock.
4. System check shows a Provider line: name, and which Twilio settings are present (values are never shown).
5. Send `STOP`, check the farmer shows as opted out; `START` to resume.

## 4. Go-live checklist
- [ ] Consent text agreed (first message records consent; the welcome explains the service).
- [ ] `STOP` and `START` tested on a real handset.
- [ ] Quiet hours (21:00 to 06:00 Kathmandu) confirmed for alerts and broadcasts.
- [ ] Cost: set `SMS_COST_PER_SEGMENT_NPR`, watch the cost card on Overview, set a spending limit in Twilio.
- [ ] Native-speaker review of every Nepali and Roman Nepali line in `app/core/templates.py`.
- [ ] `RATE_PER_MIN` and `RATE_PER_DAY` suit the pilot.
- [ ] `ADMIN_PASSWORD`, `SECRET_KEY` and `ALERTS_TOKEN` set; https on.
- [ ] A host with a persistent disk (not Vercel `/tmp`) for anything beyond a demo.

## Costs, honestly
- Replies sent by the app use your Twilio credit, per segment.
- Whether the sender pays depends on their carrier and plan. Check with your carrier.
- Trial accounts add a prefix to each message, which uses part of the 2-segment budget.
- Nepali script replies are UCS-2 (70 characters per SMS), so they use more segments than English or Roman Nepali.

## Troubleshooting
| Problem | What to check |
|---|---|
| No reply | Twilio Console, Monitor, Logs, Messaging. Webhook URL and POST. Verified number on trial. `SMS_PROVIDER=twilio`. |
| Signature fails | `PUBLIC_BASE_URL` must match the address Twilio calls exactly (https, no trailing slash), or leave it empty. |
| Wrong language | `LANG EN`, `LANG RN`, `LANG NE`, or `9` on the main menu. |
| Over 2 segments | Trial prefix, or Nepali script. Template check in the Test Console. |
| State resets | Vercel `/tmp` storage. Use a persistent host. |
| Deploy too large | Only `requirements.txt` on Vercel; keep `.vercelignore`. |
| Trial limits | Verified numbers only, prefix added. Upgrade for a pilot. |

## Roll back
Set `SMS_PROVIDER=mock` and restart or redeploy.

## What changes and what stays
| Changes | Stays the same |
|---|---|
| `SMS_PROVIDER` and its settings | Engine, flows, templates, understanding, models |
| Webhook URLs in the provider console | Outbox, retries, receipts, idempotency |
| `PUBLIC_BASE_URL`, `SMS_VERIFY_SIGNATURE` | Opt-out, quiet hours, rate limits |
| Real cost per segment | Dashboard, Test Console, scenarios |

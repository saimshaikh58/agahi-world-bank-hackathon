# agahi_hackathon

**Agahi** (آگاہی, "awareness") is an SMS-first market, forecast and weather advisor for farmers and traders selling into Kalimati wholesale market in Kathmandu. A farmer texts a number, picks their district, then uses a numbered menu or short free text (`golbheda`, `alu 2 hapta`, `becham kauli 300kg`) to get today's wholesale price, a forecast range for 7 days to 3 months with an honest reliability label, weather for their own district, and a sell or hold hint. Everything fits in at most two SMS, works in English, Roman Nepali and Nepali, and runs on small models trained on local data with no LLM at runtime.

It ships with a web simulator that behaves exactly like SMS, an operations dashboard, and a working Twilio connection for real SMS. The simulator (`SMS_PROVIDER=mock`) is the default; real SMS is switched on with a few settings (see "Deploy and connect" below).

A plain-English guide to every model, for judges and non-technical readers: [docs/Agahi_Model_Guide.docx](docs/Agahi_Model_Guide.docx).

## Quick start

You need Python 3.10, 3.11, 3.12 or 3.13 installed. Nothing else.

**Windows**
1. Unzip `agahi_hackathon.zip`.
2. Double-click `run.bat` (or run it from a terminal inside the folder).
3. Open http://localhost:8000/ for the chat simulator and http://localhost:8000/admin for the dashboard.

**macOS / Linux**
1. Unzip `agahi_hackathon.zip`.
2. In a terminal: `cd agahi_hackathon && ./run.sh`
3. Open http://localhost:8000/ and http://localhost:8000/admin.

The first run creates a virtual environment, installs packages (`requirements-train.txt`, which includes the runtime list in `requirements.txt`), loads the bundled Kalimati data, trains every model in fast mode (about 2 to 3 minutes on a laptop) and seeds demo conversations. Later runs start in seconds. The terminal prints the URLs and the admin password.

- **Default admin password:** `agahi-admin`. Change `ADMIN_PASSWORD` in `.env` before showing the dashboard to anyone.
- **Data included:** `data/kalimati_bundle.zip` holds the real Kalimati scrape (prices 2023-08-01 to 2026-10-03, 13 crops) and the GEE weather file (2015-01-01 to 2026-09-24, 6 districts plus the area average).
- **SAMPLE DATA banner:** if the real bundle is missing, the app generates a small synthetic dataset instead and shows an amber "SAMPLE DATA, not real prices" banner in the chat and dashboard, and prefixes replies with `[SAMPLE]`, until a real ZIP is uploaded.
- **Demo data banner:** about 14 days of demo conversations are seeded so the dashboard has something to show. They are marked as demo everywhere and can be purged with one click.

## Deploy and connect (GitHub, Vercel, Twilio)

Follow these steps in order. You can test everything for free first in the Test Console (dashboard, Test Console, Chat test), which never sends a real SMS.

**1. Twilio account and number**
1. Sign up at twilio.com. Note the **Account SID** and **Auth Token** on the Console home page.
2. Buy or claim a phone number with SMS (Phone Numbers, Manage, Buy a number). Write it in E.164 form, for example `+15005550006`.
3. Trial accounts can only send to phone numbers you have verified. Go to Phone Numbers, Manage, Verified Caller IDs and add your own phone.

**2. Prepare locally**
```
./run.sh                         # or run.bat; trains the models the first time
python scripts/prepare_deploy.py # copies the trained database, models and reports into deploy_assets/
```
Run `prepare_deploy.py` again every time you retrain, before you push.

**3. Put the code on GitHub**
Create an empty repository on github.com (no README), then in the project folder:
```
git init
git add .
git commit -m "Agahi hackathon"
git branch -M main
git remote add origin https://github.com/<your-user>/agahi_hackathon.git
git push -u origin main
```
`.gitignore` keeps `.env`, `.venv`, the local database, logs and trained models out; `deploy_assets/` is committed on purpose.

**4. Deploy on Vercel**
1. vercel.com, Add New, Project, import the GitHub repository. Leave the framework as Other; `vercel.json` is already set.
2. Add these Environment Variables before the first deploy:

| Name | Value |
|---|---|
| `SMS_PROVIDER` | `twilio` (or `mock` to keep it simulated) |
| `TWILIO_ACCOUNT_SID` | from the Twilio Console |
| `TWILIO_AUTH_TOKEN` | from the Twilio Console |
| `TWILIO_PHONE_NUMBER` | your Twilio number, E.164, for example `+15005550006` |
| `PUBLIC_BASE_URL` | your Vercel address, for example `https://agahi-demo.vercel.app` (no slash at the end) |
| `ADMIN_PASSWORD` | a password of your choice |
| `SECRET_KEY` | any long random text (recommended). If you leave it out, a stable key is derived from `ADMIN_PASSWORD`, so admin logins still work on every instance |
| `CRON_SECRET` | any long random text. Vercel Cron sends it to `/api/jobs/fetch` every day (you can also use `FETCH_TOKEN`) |
| `ALERTS_TOKEN` | any long random text, used to run the alerts job from a scheduler |

3. Click Deploy. Open `<vercel domain>/health`: it should say `"status": "ok"`.

**Daily data on Vercel (read this).** On Vercel the database lives in `/tmp` and is wiped on every cold start. A cold start loads the bundled data from `deploy_assets/`, and the first request of the day then fetches the missing Kalimati days (a few per request, with short timeouts) and updates today's estimates with the trained models. No retraining happens on Vercel. `vercel.json` also has a daily cron entry (`/api/jobs/fetch` at 03:30 UTC, 09:15 Nepal time); the Vercel Hobby plan allows one daily cron. Because `/tmp` is not kept, days fetched on Vercel are lost on the next cold start and fetched again, so redeploy with fresh `deploy_assets/` now and then (run the app locally, click **Fetch new data**, then `python scripts/prepare_deploy.py`). The admin **Data & training** page has the same **Fetch new data** button and shows rows added, the latest date and any error. If the Kalimati site cannot be reached, the old data stays and the error is shown there.

**5. Point Twilio at the app**
Twilio Console, Phone Numbers, Manage, Active Numbers, click your number, Messaging Configuration:
- A MESSAGE COMES IN: Webhook, URL `<vercel domain>/api/sms/inbound`, HTTP POST. Save.
- Status callback URL (same page, if shown): `<vercel domain>/api/sms/status`. Replies sent by the app already ask Twilio to report back there.

**6. Test**
Send `1` (or `golbheda`) from your verified phone to the Twilio number. You should get the welcome or the location list back. Then open `<vercel domain>/admin`, SMS operations: the webhook log shows the message and the outbox shows the reply. Conversations shows the chat.

**7. Roll back**
Set `SMS_PROVIDER=mock` in Vercel and redeploy. The simulator keeps working; Twilio messages stop being answered.

**Costs, honestly**
- Every reply the app sends uses your Twilio credit. Twilio charges per SMS segment, and prices depend on the destination country.
- Whether the farmer pays to send a message to your number depends on their carrier and plan. Check with your carrier. We do not promise it is free for the sender.
- Trial accounts add a short prefix ("Sent from your Twilio trial account") to every message. That uses part of the 2-segment budget, so some replies become 2 or 3 segments on trial.
- Nepali script (Devanagari) replies use UCS-2, which fits 70 characters per SMS instead of 160, so they cost more segments than English or Roman Nepali.
- Testing in the Test Console and the web simulator is free.

**What Vercel can and cannot do here**
The Vercel setup was checked by simulating Vercel locally (the `VERCEL` setting, a read-only project folder, `/tmp` storage, no scikit-learn installed). It has not been deployed to a real Vercel account, so treat it as untested until your first deploy works.
- Vercel can only write to `/tmp`. The app copies `deploy_assets/` there on a cold start, so prices, forecasts and the dashboard work straight away.
- Farmers, sessions and conversations live in that `/tmp` SQLite file, so they reset when Vercel starts a new instance and can differ between instances. That is fine for a demo, not for production. For production use a host with a persistent disk (a small VM, Render or Railway with a volume, Fly.io with a volume) or move the database to Postgres.
- No background work on Vercel: training is switched off ("train locally, run prepare_deploy, redeploy"), and queued messages (alerts, broadcasts, operator replies) are sent inside the same request. Alerts run only when something calls `POST /api/jobs/alerts` with the header `Authorization: Bearer <ALERTS_TOKEN>`.
- Live updates on the dashboard switch to checking every 5 seconds, because long-lived connections do not hold on serverless.
- Size: the runtime packages in `requirements.txt` measured 198 to 214 MB installed (Python 3.12, Linux; the higher figure includes pip in a fresh virtual environment), under Vercel's 250 MB function limit. With scikit-learn the same install was 392 MB, so scikit-learn is training-only (`requirements-train.txt`) and the web app runs the trained intent model through a NumPy copy. The project files Vercel uploads (after `.vercelignore`) measured about 17 MB including `deploy_assets/`. If a future change pushes it over, the smallest fix is to drop `Pillow` (the logo colours fall back to the hard-coded brand colours).

**Troubleshooting real SMS**

| Problem | What to check |
|---|---|
| No reply on the phone | Twilio Console, Monitor, Logs, Messaging: did the webhook return 200? Is the number on your Verified Caller IDs (trial)? Is `SMS_PROVIDER=twilio`? |
| Signature fails (403, "bad signature" in the webhook log) | `PUBLIC_BASE_URL` must be exactly the address Twilio calls, `https://`, no slash at the end. Leave it empty to use the forwarded host instead. `SMS_VERIFY_SIGNATURE=false` only for a quick test. |
| Replies in the wrong language | Text `LANG EN`, `LANG RN` or `LANG NE`, or `9` on the main menu. The choice is saved per phone. |
| Reply longer than 2 segments | Trial prefix (see costs) or Nepali script. Run the Test Console Template check: all templates fit without the trial prefix. |
| Farmers and chats reset | Expected on Vercel (`/tmp` storage). Use a host with a persistent disk for real use. |
| Deploy too large | Make sure Vercel installs `requirements.txt` only, and that `.vercelignore` is in the repo. |
| Twilio trial limits | Trial accounts only reach verified numbers and add a prefix. Upgrade the account for a pilot. |
| STOP does not get our reply | Twilio handles STOP, START and HELP itself on most numbers and sends its own reply. The app still records the opt-out. |

## Use your own (newer) data

1. Build one ZIP with the scraper and GEE CSVs. File names do not matter: files are recognised by their columns (anchor series, daily by crop, variant coverage, arrivals, weather).
2. Dashboard, **Data & training**, drop the ZIP on the upload box. You get a validation report: files detected, rows, date ranges, per-crop day counts, missing days, carried-over share, weather coverage and the detected location list.
3. Click **Train all** (fast about 3 minutes, full up to 15 minutes). Progress and the log stream live; you can cancel.

Command line equivalent: `python scripts/ingest_zip.py bundle.zip` then `python scripts/train_all.py fast`.

**Locations come from the weather file.** Every `location` value becomes a farmer location, except `boundary_mean`, which is the whole-area average used for market-level model features and for farmers who answer "Not sure". Known keys get display names in three languages and coordinates for the live forecast; an unknown key is humanised and served from history and climatology only, labelled as such.

## Guided tour

**Chat simulator (`/`).** Press **New farmer** to get a fresh number, then:
1. Send anything: you get the welcome. Send `1`: you get the location list from the weather file. Send `4`: Dhading is saved and the main menu appears.
2. Tap the numbered chips, use the quick options above the keypad (Price, Forecast, Weather, Sell/Hold, Arrivals), or type: `golbheda`, `tomato 14 din`, `alu 2 hapta`, `next month rain`, `becham alu 500kg`, then follow-ups like `and potato?`, `ani?`, `aru?`.
3. Under every reply: a two-cell meter shows how much of the 2-SMS budget it used, with encoding and character count. "How this reply was made" opens the trace: state change, intent probabilities, slots, data used, model and status, dropped parts, latency.
4. EN / RN / NE switch the reply language (the same as texting `LANG EN`). Offline mode answers from cached data only and adds "as of <date>".

**Dashboard (`/admin`).**
- **Overview:** messages, farmers, onboarding completion, segments per reply, p50/p95 latency, unknown-intent rate, estimated SMS cost, charts by language, intent, crop, location, hour and weekday.
- **Conversations:** live inbox (Server-Sent Events) with filters by language, intent, location; every bot message carries its trace; operators can reply through the outbox.
- **Market & forecasts:** price history with min/max band and the forecast fan (P10 to P90, the 80% range), forecast table with the 50% range shown to farmers next to the 80% range, arrivals and rain aligned beneath, variant comparison, weather-market lagged correlation, forecast table, data health.
- **Models & evaluation:** status matrix (crop x horizon), per-cell backtest (actual vs predicted, error by horizon vs baselines, interval calibration, residuals, permutation importance, live accuracy), weather model skill, intent accuracy and confusion matrix, model footprint, model card download.
- **Data & training:** upload, validation report, versions, system check, Train all.
- **Test Console:** the five things to try:
  1. **Chat test** with a side debug trace.
  2. **Forecast tester:** pick a crop and horizon, see the 50% range shown to farmers, P50 and the 80% range, status, every model's backtest numbers and the exact SMS in all three languages with segment counters.
  3. **Weather tester:** location and horizon, values, method and SMS text.
  4. **Scenario runner:** 37 scripted conversations through the real engine (onboarding, invalid replies, STOP and LANG mid-onboarding, every menu path, `0` from every screen, paging, free text, typos). Click **Run all**.
  5. **Template check:** renders every template for 13 crops x 7 horizons x every location x 3 languages with worst-case numbers and flags anything over 2 segments.
- **Weather outlook, Farmers, Alerts & broadcast, SMS operations, Quality queue** for the operational side (masked phone numbers, quiet hours, opt-outs, outbox funnel, unknown messages to turn into aliases).

## Troubleshooting

| Problem | Fix |
|---|---|
| Real SMS problems | See "Troubleshooting real SMS" above. |
| Port 8000 busy | The run script switches to 8001 automatically. Or set `PORT=` in `.env`. |
| `pip install` fails | Check internet access and Python version (3.10 to 3.13, 64-bit). Delete `.venv` and run again. |
| No internet | Everything works. Weather uses climatology and says so in the reply; the system check marks Open-Meteo unreachable. |
| Charts are empty boxes | Chart.js is bundled in `app/static/js/vendor/`. If you deleted it, the page uses the jsDelivr CDN; if that is blocked, tables still show every number. To re-vendor: download `chart.umd.min.js` from `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js` into `app/static/js/vendor/`. |
| Replies say "forecast not trained yet" | Dashboard, Data & training, Train all (or `python scripts/train_all.py`). |
| Location list empty | The weather file was missing from the ZIP. Upload a bundle that includes it. |
| Dashboard login fails | The password is `ADMIN_PASSWORD` in `.env` (default `agahi-admin`). Five wrong tries lock login for 5 minutes. |
| Something else | `logs/app.log` has details; `GET /health` and the System check panel show what is missing. |

## Impact and inclusion

- **Who it serves:** smallholders and small traders in the Kathmandu Valley and surrounding districts (Kavre, Nuwakot, Dhading, Sindhupalchok, Makwanpur) who sell into Kalimati and decide each week when to harvest, transport and sell.
- **Basic phones:** plain SMS, numbered menus, no app, no data plan, no links in replies.
- **Local languages:** Roman Nepali by default (what most people type on keypads), Devanagari Nepali and English; switch any time with `9` or `LANG xx`.
- **Cost aware:** every reply is held to at most two segments in code; English and Roman Nepali stay in cheap GSM-7; the dashboard estimates cost per segment.
- **Location aware:** weather and harvest or transport risk use the farmer's own district; market effects use the area average.
- **Limited connectivity:** offline mode and climatology fallback mean answers never depend on a live API.
- **Small models:** see the footprint below. No GPU, no LLM, no paid API.

No impact numbers are claimed. Every figure in the app and in this README comes from the data or from the evaluation reports.

## What is used

**Libraries:** FastAPI, Uvicorn, SQLite, Jinja2, vanilla JavaScript, Chart.js 4.4.1 (vendored), pandas, NumPy, joblib, RapidFuzz, httpx, Pillow at runtime; scikit-learn, pytest and python-docx for training, tests and the model guide.

**Price forecasting** (`app/forecast`): per crop, the primary variant from the anchor series; carried-over days set to missing; gaps up to 3 days filled. Targets: `log(P[t+h]/P[t])` for 7, 14, 21, 28 days and the log of the 7-day mean around 30, 60, 90 days for months 1 to 3. Features at origin t use only data up to t: returns over 1 to 28 days, z-score vs the 90-day mean, 14-day volatility, arrivals z-score and 7/28-day ratio, area rain sums and rainy-day counts over 3 to 28 days, mean Tmax, day of year, the gap to the second variant. Future weather forecasts are not features (there is no archive to backtest them).

Candidates per crop and horizon: persistence, seasonal-naive (same day of year in earlier years only), mean reversion, Ridge, a small HistGradientBoostingRegressor (median, depth 3), and a shrinkage blend of the best baseline and the boosted model. **Validation:** expanding-window walk-forward, first window at least 365 days, 60-day test blocks in fast mode (30 in full), embargo of h days between train and test. **Intervals:** split-conformal on out-of-fold residuals, each test block calibrated only on earlier blocks. **Status gate:** `reliable` needs skill vs the best baseline of at least 5%, direction accuracy of at least 58%, calibrated 80% coverage between 70% and 90% and at least 60 test origins; `indicative` needs a learned model with non-negative skill and acceptable coverage; anything else is `pattern only` (a seasonal range); too little data is `unavailable`. Months 1 to 3 can never exceed `indicative`. These statuses are internal only. Farmers always read "rough estimate" for prices ("rough estimate from past years" for pattern-only cells) and "estimated" for weather. The sell or hold advisor only uses 7 or 14 day forecasts that are `reliable`; otherwise it uses trend and weather rules, and its wording also says rough estimate. Confidence is never "high".

**Ranges:** farmers see a "likely range" from a calibrated 50% interval (P25 to P75, split-conformal like the 80% one), clipped so it is never negative and stays within the crop's historical low and high for that time of year, rounded to the nearest Rs5, and never wider than the 80% range. The shorter range is right about half the time; the wide range (P10 to P90, kept in the admin) about 8 times in 10. Both backtest coverages are reported.

**Weather** (`app/weather`): per-location day-of-year climatology (smoothed plus or minus 7 days); Open-Meteo for days 1 to 7 (free, no key, 3 hour cache, 5 second timeout, climatology fallback); Ridge models for weekly aggregates in weeks 2 to 4, backtested against climatology by year with a 28-day embargo and kept only with at least 3% skill; months 1 to 3 are climatology with tercile probabilities nudged by the last 30 days.

**Understanding messages** (`app/core`): cleaning (Nepali digits, spelling merges, repeated letters, SMS shorthand such as `tmrw` and `kti`, Nepali word endings), alias dictionaries in three scripts, RapidFuzz spell correction with a guard for ambiguous matches, extraction of crop, time ahead, district, quantity, variety and time words (`aaja`, `bholi`, `parsi`, `hijo`, `next week`, `yo hapta`) from one sentence, and memory for follow-ups (`and potato?`, `ani?`, `aru?`, `kati ho?`). The intent classifier uses TF-IDF word 1-2 grams plus character 2-5 grams; logistic regression and a calibrated linear SVM are compared by cross-validation and the better one is kept. It is trained on `data/nlu_training.jsonl` (9,240 generated examples, 220 per intent per language, with typos, dropped vowels, repeated letters, shorthand, mixed English and Roman Nepali and casual sentences) and checked on `data/nlu_casual_test.jsonl` (162 hand-written casual and noisy messages). The web app runs a NumPy copy of the trained model (about 1 MB). Replies are plain-language templates, one idea per line, with numbered options on their own lines.

**Where results are saved:** SQLite (`data/agahi.db`: backtest results, test predictions, forecasts, forecast ledger, weather backtests and outlooks, intent evaluation, messages, outbox), artifacts in `models/`, and `reports/` (`backtest_price.csv`, `backtest_weather.csv`, `intent_eval.json`, `weather_market_corr.json`, `training_log.txt`, `model_card.md`).

**Reading the Models page:** green cells are `reliable`, amber `indicative`, grey `pattern only`, red `unavailable`; the number is skill against the best baseline. Click a cell for its full backtest.

## Latest results

Generated by `scripts/export_report.py` from the saved evaluation of the bundled data. Your first run retrains with the same seeds.

<!-- RESULTS:START -->
Run 9 (fast mode), finished 2026-10-04T17:22:45+05:45. Dataset v1, prices 2023-08-01 to 2026-10-03.

- Forecast cells (crop x horizon): 91; status counts: indicative: 25, pattern only: 50, reliable: 16
- Weather weeks 2-4 cells that beat climatology by >= 3%: 0 of 84
- Intent classifier held-out accuracy: 99.4% (logistic_regression); hand-written casual set (162 messages, whole NLU): 97.5%
- Model footprint: 91 price artifacts, 1991 KB total; median CPU inference 0.66 ms; intent model 981 KB
- Farmers see the shorter 50% range (right about half the time); the wide 80% range is right about 8 times in 10.

| crop | horizon | chosen model | status | skill vs best baseline | 80% coverage | 50% coverage | direction acc. | test origins |
|---|---|---|---|---|---|---|---|---|
| beans | d7 | blend | indicative | 0.1% | 72.3% | 45.2% | 57.7% | 788 |
| beans | d14 | mean_reversion | pattern only | 0.0% | 67.8% | 42.3% | 64.0% | 781 |
| beans | d21 | mean_reversion | pattern only | 0.0% | 66.5% | 41.5% | 68.4% | 774 |
| beans | d28 | mean_reversion | pattern only | 0.0% | 65.1% | 42.0% | 70.8% | 767 |
| beans | m1 | mean_reversion | pattern only | 0.0% | 61.4% | 44.2% | 71.2% | 762 |
| beans | m2 | mean_reversion | pattern only | 0.0% | 68.9% | 42.3% | 68.9% | 732 |
| beans | m3 | mean_reversion | pattern only | 0.0% | 62.3% | 38.8% | 66.7% | 702 |
| bitter_gourd | d7 | hgb | indicative | 4.6% | 79.1% | 55.6% | 66.3% | 788 |
| bitter_gourd | d14 | hgb | reliable | 5.7% | 74.5% | 46.5% | 67.0% | 781 |
| bitter_gourd | d21 | hgb | reliable | 11.6% | 75.2% | 41.6% | 69.2% | 774 |
| bitter_gourd | d28 | ridge | pattern only | 18.6% | 69.2% | 37.1% | 72.3% | 767 |
| bitter_gourd | m1 | ridge | pattern only | 23.3% | 64.8% | 33.5% | 76.0% | 762 |
| bitter_gourd | m2 | ridge | pattern only | 29.5% | 69.3% | 38.4% | 85.3% | 732 |
| bitter_gourd | m3 | ridge | pattern only | 25.5% | 60.4% | 35.0% | 82.3% | 702 |
| cabbage | d7 | persistence | pattern only | 0.0% | 77.6% | 49.3% | 0.0% | 788 |
| cabbage | d14 | blend | indicative | 0.4% | 72.4% | 43.4% | 30.2% | 781 |
| cabbage | d21 | blend | indicative | 2.0% | 72.7% | 43.4% | 39.2% | 774 |
| cabbage | d28 | blend | indicative | 0.5% | 74.5% | 39.7% | 31.1% | 767 |
| cabbage | m1 | persistence | pattern only | 0.0% | 72.1% | 37.7% | 0.0% | 762 |
| cabbage | m2 | hgb | indicative | 16.2% | 75.4% | 54.9% | 74.7% | 732 |
| cabbage | m3 | hgb | indicative | 12.0% | 72.9% | 43.0% | 75.7% | 702 |
| carrot | d7 | persistence | pattern only | 0.0% | 80.8% | 55.5% | 0.0% | 788 |
| carrot | d14 | hgb | indicative | 4.4% | 77.1% | 54.8% | 69.7% | 781 |
| carrot | d21 | hgb | reliable | 8.3% | 81.8% | 54.2% | 74.8% | 774 |
| carrot | d28 | blend | reliable | 8.5% | 80.8% | 52.3% | 77.0% | 767 |
| carrot | m1 | hgb | indicative | 9.0% | 82.9% | 53.4% | 77.4% | 762 |
| carrot | m2 | hgb | indicative | 10.5% | 86.3% | 70.4% | 81.4% | 732 |
| carrot | m3 | hgb | indicative | 6.0% | 81.6% | 68.5% | 82.7% | 702 |
| cauliflower | d7 | hgb | reliable | 6.4% | 75.5% | 43.5% | 64.9% | 788 |
| cauliflower | d14 | hgb | reliable | 10.0% | 73.6% | 42.0% | 68.6% | 781 |
| cauliflower | d21 | hgb | reliable | 6.8% | 76.5% | 53.1% | 69.0% | 774 |
| cauliflower | d28 | hgb | reliable | 8.0% | 78.1% | 56.6% | 71.7% | 767 |
| cauliflower | m1 | hgb | indicative | 12.5% | 77.8% | 52.3% | 75.0% | 762 |
| cauliflower | m2 | blend | indicative | 10.7% | 81.1% | 50.4% | 73.2% | 732 |
| cauliflower | m3 | hgb | indicative | 21.8% | 88.0% | 69.6% | 86.9% | 702 |
| eggplant | d7 | hgb | indicative | 1.6% | 78.4% | 46.6% | 65.0% | 788 |
| eggplant | d14 | mean_reversion | pattern only | 0.0% | 76.0% | 42.9% | 65.5% | 781 |
| eggplant | d21 | mean_reversion | pattern only | 0.0% | 74.5% | 50.6% | 64.5% | 774 |
| eggplant | d28 | mean_reversion | pattern only | 0.0% | 73.4% | 54.3% | 66.1% | 767 |
| eggplant | m1 | mean_reversion | pattern only | 0.0% | 74.1% | 55.8% | 66.0% | 762 |
| eggplant | m2 | mean_reversion | pattern only | 0.0% | 68.3% | 47.9% | 67.9% | 732 |
| eggplant | m3 | mean_reversion | pattern only | 0.0% | 67.4% | 40.3% | 60.3% | 702 |
| okra | d7 | hgb | reliable | 5.6% | 79.7% | 48.4% | 66.3% | 788 |
| okra | d14 | hgb | reliable | 9.0% | 78.4% | 45.9% | 66.0% | 781 |
| okra | d21 | hgb | reliable | 13.4% | 78.6% | 52.7% | 72.9% | 774 |
| okra | d28 | blend | reliable | 19.0% | 78.5% | 53.2% | 75.5% | 767 |
| okra | m1 | blend | indicative | 19.7% | 78.8% | 49.0% | 73.9% | 762 |
| okra | m2 | hgb | pattern only | 16.2% | 69.5% | 42.1% | 83.5% | 732 |
| okra | m3 | ridge | indicative | 20.9% | 76.6% | 50.0% | 84.6% | 702 |
| onion_dry | d7 | persistence | pattern only | 0.0% | 83.7% | 58.0% | 0.0% | 788 |
| onion_dry | d14 | persistence | pattern only | 0.0% | 85.0% | 54.9% | 0.0% | 781 |
| onion_dry | d21 | persistence | pattern only | 0.0% | 80.4% | 53.4% | 0.0% | 774 |
| onion_dry | d28 | persistence | pattern only | 0.0% | 75.7% | 56.2% | 0.0% | 767 |
| onion_dry | m1 | persistence | pattern only | 0.0% | 74.8% | 54.3% | 0.0% | 762 |
| onion_dry | m2 | persistence | pattern only | 0.0% | 60.0% | 39.4% | 0.0% | 732 |
| onion_dry | m3 | persistence | pattern only | 0.0% | 64.5% | 33.2% | 0.0% | 702 |
| peas | d7 | persistence | pattern only | 0.0% | 80.3% | 55.0% | 0.0% | 537 |
| peas | d14 | hgb | indicative | 4.2% | 81.0% | 60.4% | 66.0% | 535 |
| peas | d21 | hgb | reliable | 12.1% | 78.6% | 55.1% | 70.8% | 518 |
| peas | d28 | hgb | reliable | 18.7% | 79.1% | 58.0% | 79.3% | 505 |
| peas | m1 | hgb | indicative | 19.3% | 81.1% | 57.5% | 80.0% | 500 |
| peas | m2 | hgb | indicative | 35.8% | 77.7% | 62.0% | 90.3% | 450 |
| peas | m3 | ridge | pattern only | 13.2% | 49.8% | 25.1% | 87.5% | 299 |
| potato | d7 | mean_reversion | pattern only | 0.0% | 72.9% | 41.9% | 70.8% | 788 |
| potato | d14 | blend | pattern only | 0.6% | 69.5% | 39.5% | 77.9% | 781 |
| potato | d21 | hgb | reliable | 12.9% | 71.3% | 46.9% | 79.1% | 774 |
| potato | d28 | hgb | pattern only | 7.2% | 69.6% | 42.0% | 73.7% | 767 |
| potato | m1 | blend | pattern only | 9.0% | 67.8% | 39.5% | 85.8% | 762 |
| potato | m2 | seasonal_naive | pattern only | 0.0% | 61.0% | 38.2% | 87.4% | 732 |
| potato | m3 | seasonal_naive | pattern only | 0.0% | 68.7% | 41.7% | 85.4% | 702 |
| pumpkin | d7 | persistence | pattern only | 0.0% | 85.6% | 59.2% | 0.0% | 788 |
| pumpkin | d14 | persistence | pattern only | 0.0% | 85.4% | 57.7% | 0.0% | 781 |
| pumpkin | d21 | persistence | pattern only | 0.0% | 82.5% | 60.9% | 0.0% | 774 |
| pumpkin | d28 | persistence | pattern only | 0.0% | 81.8% | 59.7% | 0.0% | 767 |
| pumpkin | m1 | mean_reversion | pattern only | 0.0% | 79.1% | 51.1% | 62.4% | 762 |
| pumpkin | m2 | mean_reversion | pattern only | 0.0% | 75.7% | 49.4% | 61.6% | 732 |
| pumpkin | m3 | mean_reversion | pattern only | 0.0% | 71.5% | 39.6% | 70.4% | 702 |
| radish | d7 | persistence | pattern only | 0.0% | 80.9% | 51.7% | 0.0% | 784 |
| radish | d14 | persistence | pattern only | 0.0% | 76.7% | 49.5% | 0.0% | 777 |
| radish | d21 | blend | indicative | 0.6% | 77.2% | 51.4% | 46.3% | 770 |
| radish | d28 | persistence | pattern only | 0.0% | 72.5% | 51.5% | 0.0% | 763 |
| radish | m1 | persistence | pattern only | 0.0% | 72.4% | 52.0% | 0.0% | 760 |
| radish | m2 | ridge | pattern only | 18.5% | 66.1% | 37.5% | 67.4% | 730 |
| radish | m3 | ridge | pattern only | 30.7% | 68.0% | 43.6% | 72.7% | 700 |
| tomato | d7 | hgb | indicative | 4.4% | 78.4% | 50.6% | 59.0% | 718 |
| tomato | d14 | persistence | pattern only | 0.0% | 83.5% | 49.2% | 0.0% | 704 |
| tomato | d21 | hgb | indicative | 3.3% | 80.2% | 51.7% | 68.4% | 690 |
| tomato | d28 | hgb | reliable | 7.9% | 80.4% | 53.4% | 71.0% | 676 |
| tomato | m1 | hgb | indicative | 12.2% | 78.7% | 52.2% | 74.5% | 669 |
| tomato | m2 | ridge | indicative | 12.9% | 71.8% | 35.8% | 82.3% | 627 |
| tomato | m3 | mean_reversion | pattern only | 0.0% | 79.1% | 53.3% | 68.6% | 597 |
<!-- RESULTS:END -->

## Limitations and trade-offs

- Prices are Kalimati **wholesale**, not farm-gate. A farmer's price is lower by transport and margins.
- Arrivals include Indian imports, so they are a market-supply signal, not local harvest.
- Price history is just over 3 years, so months 1 to 3 are seasonal outlooks only, and many crop and horizon cells are honestly `pattern only`.
- Weather beyond about two weeks is climatology. In our backtests no weekly model beat climatology by 3%, so weeks 2 to 4 are served as climatology.
- The bundled weather file ends 2026-09-24; live weather needs internet.
- Location detail is limited to the six weather points plus the area average.
- Nepali and Roman Nepali text was not reviewed by a native speaker; it must be before any pilot.
- Twilio was tested against recorded request formats with the network mocked, not against a live Twilio account from here.
- On Vercel, farmers and conversations reset with each new instance (see "What Vercel can and cannot do here").
- The intent classifier is trained on generated examples, so real farmer messages will surface new phrasings; the Quality queue exists for that.

## Next steps

1. Real SMS: connect Twilio as in "Deploy and connect", then move to a host with a persistent disk for a pilot.
2. Pilot with one farmer group in one district; native-speaker review of all strings first.
3. Retrain weekly as new scraper data arrives; watch live accuracy on the Models page.
4. Voice (IVR) later, for farmers who do not read SMS.

## Folder map

```
agahi_hackathon/
  run.sh, run.bat           one-command start
  requirements.txt          runtime packages (web app, Vercel)
  requirements-train.txt    adds scikit-learn, pytest and python-docx for training, tests and the model guide
  vercel.json, .vercelignore  Vercel settings
  deploy_assets/            trained database, models and reports for Vercel (made by scripts/prepare_deploy.py)
  app/                      the application (FastAPI)
    core/                   SMS budget, aliases, NLU, intent model, templates, flows, engine, advisor
    forecast/               price features, baselines, models, walk-forward backtest, conformal, registry
    weather/                climatology, Open-Meteo, weeks 2-4 models, outlooks
    ingest/                 ZIP ingestion and validation
    sms/                    providers (mock, Android gateway, Twilio), outbox, inbound, alerts, compliance
    channels/, api/         web pages, chat API, SMS webhooks, admin API
    templates/, static/     HTML, CSS, JS, logo, vendored Chart.js
  scripts/                  first run, training, ingestion, sample data, smoke test, prepare_deploy, model guide, packaging
  data/                     bundled Kalimati ZIP, NLU training data, database (created on first run)
  models/, reports/, logs/  created by training and running
  tests/                    pytest suite (runs offline)
  docs/                     model guide (Word), API contract, guide, architecture, model card, flows, SMS migration, demo script
```

## Tests

```
python -m pytest -q                 # offline, about 35 seconds
python scripts/smoke_test.py         # starts a server and checks every route, the flows and training
```

## Credits

Built for the "Small AI for Development" hackathon (agriculture track) by the Agahi Intelligence team. Prices scraped from public Kalimati market reports; weather from Google Earth Engine reanalysis; live forecasts from Open-Meteo. Chart.js is MIT licensed.

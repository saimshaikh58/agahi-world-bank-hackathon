# Operating guide

## Daily operation
1. New scraper and GEE files arrive: zip them together (any file names).
2. Dashboard, **Data & training**: upload. Read the validation report: warnings are shown in amber. A missing optional file (arrivals, variant coverage) is a warning, not a failure.
3. Click **Train all** (fast mode is fine for daily updates; use full mode weekly). Training runs in the background; one job at a time; you can cancel; a crash is recorded in the job log and never stops the server.
4. Check **Models & evaluation**: the status matrix, and **Live accuracy** for each cell (realised prices fill in as new data arrives).
5. **Quality queue**: messages the bot did not understand. Save crop words as aliases; they work from the next message.

## Command line
| Task | Command |
|---|---|
| First-run setup (idempotent) | `python scripts/first_run.py` |
| Ingest a ZIP | `python scripts/ingest_zip.py bundle.zip` |
| Train everything | `python scripts/train_all.py fast` or `full` |
| Price backtests only | `python scripts/backtest_price.py fast` |
| Weather models only | `python scripts/train_weather.py` |
| Intent classifier only | `python scripts/train_intent.py` |
| Regenerate NLU training data | `python scripts/make_nlu_data.py` |
| Generate synthetic sample data | `python scripts/make_sample_data.py` |
| Rewrite model card + README results | `python scripts/export_report.py` |
| Smoke test (starts its own server) | `python scripts/smoke_test.py` |
| Copy trained files for Vercel | `python scripts/prepare_deploy.py` |
| Write the Word model guide | `python scripts/make_model_doc.py` |
| Package the ZIP | `python scripts/package.py` |
| Tests | `python -m pytest -q` |

## Configuration
All settings are environment variables documented in `.env.example`. The app starts with zero configuration. Change `ADMIN_PASSWORD` before sharing.

## Free deployment notes
For Vercel and Twilio, follow "Deploy and connect" in the README.

- Any small VM or free tier that runs Python works (1 vCPU, 1 GB RAM is enough). Start with `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- SQLite needs a **persistent disk**: platforms with ephemeral file systems lose the database on restart. Mount a volume at `data/` (and `models/`, `reports/`) or set `AGAHI_DB` to a path on the volume.
- Put the app behind HTTPS (most platforms do this) before connecting an SMS provider, and set `PUBLIC_BASE_URL`.
- Run a single worker process: the training job manager and the outbox worker live in-process.

## Backups
Copy `data/agahi.db` (with the app stopped, or use `sqlite3 data/agahi.db ".backup backup.db"`), plus `models/` and `reports/` if you do not want to retrain.

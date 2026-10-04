"""SQLite access: WAL, foreign keys, idempotent schema, small helpers. One connection per call site."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import settings

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS dataset_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, checksum TEXT, is_sample INTEGER,
  path TEXT, report_json TEXT, active INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS locations (
  key TEXT PRIMARY KEY, name_en TEXT, name_rn TEXT, name_ne TEXT, lat REAL, lon REAL,
  sort_order INTEGER, selectable INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS prices (
  date TEXT, crop TEXT, variant TEXT, origin TEXT, size TEXT, min_kg REAL, max_kg REAL, avg_kg REAL,
  carried_over INTEGER, is_primary INTEGER, PRIMARY KEY (date, crop, variant));
CREATE TABLE IF NOT EXISTS daily_crop (
  date TEXT, crop TEXT, avg_kg REAL, min_kg REAL, max_kg REAL, n_variants REAL, carried_over INTEGER,
  arrivals_kg REAL, PRIMARY KEY (date, crop));
CREATE TABLE IF NOT EXISTS weather (
  date TEXT, location TEXT, tmin REAL, tmax REAL, rain REAL, wind REAL, heat_index REAL,
  PRIMARY KEY (date, location));
CREATE TABLE IF NOT EXISTS farmers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, lang TEXT DEFAULT 'rn', location TEXT,
  onboarding_state TEXT DEFAULT 'NEW', subscribed INTEGER DEFAULT 1, consent_at TEXT,
  created_at TEXT, last_seen TEXT, demo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (phone TEXT PRIMARY KEY, ctx_json TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, phone TEXT, direction TEXT, channel TEXT, text TEXT,
  lang TEXT, intent TEXT, confidence REAL, crop TEXT, horizon TEXT, location TEXT, state TEXT,
  segments INTEGER, encoding TEXT, chars INTEGER, latency_ms REAL, trace_json TEXT,
  demo INTEGER DEFAULT 0, provider_msg_id TEXT);
CREATE INDEX IF NOT EXISTS ix_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS ix_messages_phone ON messages(phone);
CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_pid ON messages(provider_msg_id) WHERE provider_msg_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, phone TEXT, text TEXT, kind TEXT,
  status TEXT, attempts INTEGER DEFAULT 0, next_attempt_at TEXT, idempotency_key TEXT UNIQUE,
  provider TEXT, provider_msg_id TEXT, encoding TEXT, segments INTEGER, cost REAL, error TEXT,
  updated_at TEXT, demo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS webhook_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, ok INTEGER, note TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS broadcasts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, text TEXT, audience_json TEXT, recipients INTEGER);
CREATE TABLE IF NOT EXISTS alerts_log (phone TEXT, day TEXT, kind TEXT, PRIMARY KEY (phone, day));
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, status TEXT, progress REAL, log TEXT, error TEXT,
  params_json TEXT, started_at TEXT, finished_at TEXT);
CREATE TABLE IF NOT EXISTS model_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT, mode TEXT,
  data_version INTEGER, summary_json TEXT);
CREATE TABLE IF NOT EXISTS backtest_results (
  run_id INTEGER, crop TEXT, horizon TEXT, model TEXT, mae_log REAL, mae_rs REAL, mape REAL,
  dir_acc REAL, skill REAL, pinball REAL, coverage REAL, width REAL, n_test INTEGER,
  chosen INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS backtest_preds (
  run_id INTEGER, crop TEXT, horizon TEXT, origin_date TEXT, price0 REAL, actual REAL, pred REAL,
  lo REAL, hi REAL);
CREATE INDEX IF NOT EXISTS ix_bp ON backtest_preds(run_id, crop, horizon);
CREATE TABLE IF NOT EXISTS forecasts (
  run_id INTEGER, origin_date TEXT, crop TEXT, horizon TEXT, p10 REAL, p50 REAL, p90 REAL,
  price0 REAL, pct_change_p50 REAL, status TEXT, model_name TEXT, skill REAL);
CREATE TABLE IF NOT EXISTS forecast_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, logged_at TEXT, origin_date TEXT, crop TEXT, horizon TEXT,
  target_date TEXT, p10 REAL, p50 REAL, p90 REAL, price0 REAL, realised REAL, status TEXT,
  UNIQUE (origin_date, crop, horizon));
CREATE TABLE IF NOT EXISTS weather_outlook (
  origin_date TEXT, location TEXT, horizon TEXT, variable TEXT, p10 REAL, p50 REAL, p90 REAL,
  method TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS weather_backtest (
  run_id INTEGER, location TEXT, week INTEGER, variable TEXT, mae_model REAL, mae_clim REAL,
  pinball_model REAL, pinball_clim REAL, skill REAL, n INTEGER, kept INTEGER);
CREATE TABLE IF NOT EXISTS login_fails (ip TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS weather_cache (location TEXT PRIMARY KEY, fetched_at TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS intent_eval (
  run_id INTEGER, accuracy REAL, by_lang_json TEXT, confusion_json TEXT, labels_json TEXT, n_test INTEGER);
"""


def _conn(path: Path | None = None) -> sqlite3.Connection:
    p = path or settings.db_path
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Yield a connection; commit on success, rollback on error, always close."""
    c = _conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


ADDED_COLUMNS = {  # table: [(column, type)] added after the first release
    "forecasts": [("p25", "REAL"), ("p75", "REAL"), ("band_lo", "REAL"), ("band_hi", "REAL")],
    "backtest_results": [("coverage50", "REAL"), ("width50", "REAL")],
}


def migrate() -> None:
    """Create or upgrade the schema. Idempotent."""
    with connect() as c:
        c.executescript(SCHEMA)
        for table, cols in ADDED_COLUMNS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, typ in cols:
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        row = c.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            c.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))


def q(sql: str, params: tuple | list = ()) -> list[dict]:
    """Run a SELECT and return list of dicts."""
    with connect() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def q1(sql: str, params: tuple | list = ()) -> dict | None:
    """Run a SELECT and return the first row or None."""
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: tuple | list = ()) -> int:
    """Execute a write; returns lastrowid."""
    with connect() as c:
        cur = c.execute(sql, params)
        return int(cur.lastrowid or 0)


def xmany(sql: str, rows: list[tuple]) -> None:
    """Execute many writes in one transaction."""
    with connect() as c:
        c.executemany(sql, rows)


def get_meta(key: str, default: Any = None) -> Any:
    """Read a JSON value from meta."""
    r = q1("SELECT value FROM meta WHERE key=?", (key,))
    if r is None or r["value"] is None:
        return default
    try:
        return json.loads(r["value"])
    except (TypeError, ValueError):
        return default


def set_meta(key: str, value: Any) -> None:
    """Write a JSON value to meta."""
    x("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, json.dumps(value)))

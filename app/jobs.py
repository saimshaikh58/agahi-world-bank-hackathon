"""Background job manager: one training job at a time, progress in DB, cancel and timeout."""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from typing import Any, Callable

from app import db
from app.config import settings
from app.util import now_iso

log = logging.getLogger("agahi.jobs")
JOB_TIMEOUT_S = 30 * 60
_lock = threading.Lock()
_cancel: dict[int, threading.Event] = {}


class JobBusy(Exception):
    """Raised when a job of the same kind is already running."""


class JobCancelled(Exception):
    """Raised inside a job when cancel was requested or timeout hit."""


def running(kind: str) -> dict | None:
    """Return the running job of this kind, if any."""
    return db.q1("SELECT * FROM jobs WHERE kind=? AND status IN ('queued','running') ORDER BY id DESC", (kind,))


def get(job_id: int) -> dict | None:
    """Job snapshot."""
    return db.q1("SELECT * FROM jobs WHERE id=?", (job_id,))


def cancel(job_id: int) -> bool:
    """Request cancellation."""
    ev = _cancel.get(job_id)
    if ev:
        ev.set()
        return True
    return False


def _append(job_id: int, line: str, progress: float | None = None) -> None:
    with db.connect() as c:
        row = c.execute("SELECT log FROM jobs WHERE id=?", (job_id,)).fetchone()
        text = ((row["log"] if row else "") or "") + f"[{now_iso()[11:19]}] {line}\n"
        if progress is None:
            c.execute("UPDATE jobs SET log=? WHERE id=?", (text[-20000:], job_id))
        else:
            c.execute("UPDATE jobs SET log=?, progress=? WHERE id=?", (text[-20000:], progress, job_id))


def run_sync(kind: str, fn: Callable[..., Any], params: dict | None = None) -> int:
    """Create a job row and run fn in the current thread (used by CLI scripts)."""
    job_id = _create(kind, params)
    _run(job_id, fn, params or {})
    return job_id


def start(kind: str, fn: Callable[..., Any], params: dict | None = None) -> int:
    """Start fn(progress, cancelled, **params) in a daemon thread. Raises JobBusy."""
    if settings.serverless:
        raise JobBusy("Training is turned off on this host. Train locally, run scripts/prepare_deploy.py, redeploy.")
    with _lock:
        if running(kind):
            raise JobBusy(f"A {kind} job is already running")
        job_id = _create(kind, params)
    threading.Thread(target=_run, args=(job_id, fn, params or {}), daemon=True).start()
    return job_id


def _create(kind: str, params: dict | None) -> int:
    return db.x("INSERT INTO jobs(kind,status,progress,log,params_json,started_at) VALUES(?,?,?,?,?,?)",
                (kind, "running", 0.0, "", json.dumps(params or {}), now_iso()))


def _run(job_id: int, fn: Callable[..., Any], params: dict) -> None:
    ev = threading.Event()
    _cancel[job_id] = ev
    t0 = time.time()

    def progress(p: float, msg: str) -> None:
        _append(job_id, msg, max(0.0, min(1.0, p)))
        log.info("job %s: %s", job_id, msg)

    def cancelled() -> bool:
        return ev.is_set() or (time.time() - t0) > JOB_TIMEOUT_S

    try:
        fn(progress, cancelled, **params)
        status, err = ("cancelled", None) if ev.is_set() else ("done", None)
    except JobCancelled:
        status, err = "cancelled", "Cancelled or timed out"
    except Exception as e:  # a crashed job must never crash the server
        log.error("job %s failed: %s", job_id, traceback.format_exc())
        status, err = "failed", f"{type(e).__name__}: {e}"
    if status == "done":
        _append(job_id, f"Finished in {time.time() - t0:.1f}s", 1.0)
    else:
        _append(job_id, f"Stopped: {status} {err or ''}")
    db.x("UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?", (status, err, now_iso(), job_id))
    _cancel.pop(job_id, None)


def recover_stale() -> None:
    """Mark jobs left 'running' by a previous process as failed."""
    db.x("UPDATE jobs SET status='failed', error='Server restarted during job', finished_at=? "
         "WHERE status IN ('queued','running')", (now_iso(),))

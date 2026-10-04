"""End-to-end smoke test against a running server (starts one on a free port if none is given).
Usage: python scripts/smoke_test.py [--url http://localhost:8000] [--skip-train]"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import _bootstrap  # noqa: F401
import httpx

from app.config import settings

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    args = sys.argv[1:]
    url = args[args.index("--url") + 1] if "--url" in args else None
    proc = None
    if not url:
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                                cwd=str(_bootstrap.ROOT), env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                httpx.get(url + "/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.5)
    try:
        run(url, "--skip-train" in args)
    finally:
        if proc:
            proc.terminate()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")
    return 1 if failed else 0


def run(url: str, skip_train: bool) -> None:
    c = httpx.Client(base_url=url, timeout=30)
    h = c.get("/health").json()
    check("/health", h.get("status") == "ok", str(h))
    phone = c.post("/api/chat/new", json={}).json()["phone"]
    r1 = c.post("/api/chat/send", json={"phone": phone, "text": "hello"}).json()
    check("new number -> welcome", r1["state_after"] == "WELCOME", r1["text"][:60])
    r2 = c.post("/api/chat/send", json={"phone": phone, "text": "1"}).json()
    check("1 -> location prompt", r2["state_after"] == "ASK_LOCATION", r2["text"][:60])
    r3 = c.post("/api/chat/send", json={"phone": phone, "text": "4"}).json()
    check("location -> MAIN", r3["state_after"] == "MAIN", r3["text"][:60])
    r4 = c.post("/api/chat/send", json={"phone": phone, "text": "golbheda"}).json()
    check("free text golbheda -> price", r4["intent"] == "PRICE", r4["text"][:70])
    for path, want in ((["0", "1", "1"], "AFTER_PRICE"), (["0", "2", "1", "2"], "AFTER_FORECAST")):
        r = None
        for t in path:
            r = c.post("/api/chat/send", json={"phone": phone, "text": t}).json()
        check(f"menu path {' '.join(path)}", r["state_after"] == want, r["text"][:70])
    check("chat latency < 100 ms", r4["latency_ms"] < 100 or r["latency_ms"] < 100, f"{r['latency_ms']} ms")
    bad = c.post("/api/admin/login", json={"password": "wrong"})
    check("admin rejects wrong password", bad.status_code == 401)
    ok = c.post("/api/admin/login", json={"password": settings.admin_password})
    check("admin login", ok.status_code == 200)
    csrf = ok.json().get("csrf", "")
    for p in ("/api/admin/status", "/api/admin/overview?range=30d", "/api/admin/conversations", "/api/admin/market?crop=tomato",
              "/api/admin/models", "/api/admin/models/cell?crop=tomato&horizon=d7", "/api/admin/weather", "/api/admin/data",
              "/api/admin/syscheck", "/api/admin/farmers", "/api/admin/sms", "/api/admin/quality", "/api/admin/broadcasts",
              "/api/admin/test/forecast?crop=tomato&horizon=d14", "/api/admin/test/weather?location=dhading_besi&horizon=d7",
              "/api/admin/test/scenarios", "/api/admin/test/template-check", "/api/admin/farmers.csv"):
        resp = c.get(p)
        check(f"GET {p}", resp.status_code == 200, str(resp.status_code))
    nocsrf = c.post("/api/admin/test/new-farmer", json={})
    check("CSRF enforced", nocsrf.status_code == 403)
    with c.stream("GET", "/api/admin/events") as s:
        first = next(s.iter_lines())
        check("SSE connects", first.startswith("event:"), first)
    sc = c.post("/api/admin/test/scenarios/run", json={"name": None}, headers={"X-CSRF-Token": csrf}).json()
    check("scenario runner all pass", sc["passed"] == sc["total"], f"{sc['passed']}/{sc['total']}")
    if skip_train:
        return
    j = c.post("/api/admin/train", json={"mode": "fast"}, headers={"X-CSRF-Token": csrf})
    check("training job starts", j.status_code == 200, j.text[:80])
    if j.status_code == 200:
        jid = j.json()["job_id"]
        status = "running"
        for _ in range(400):
            status = c.get(f"/api/admin/jobs/{jid}").json()["status"]
            if status != "running":
                break
            time.sleep(1)
        check("training job finishes (fast)", status == "done", status)


if __name__ == "__main__":
    sys.exit(main())

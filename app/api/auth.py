"""Admin auth: password login (constant-time), signed HttpOnly cookie, CSRF token, login rate limit."""
from __future__ import annotations

import hashlib
import hmac
import time
from collections import defaultdict, deque

from fastapi import Request

from app.api.errors import ApiError
from app.config import settings

COOKIE = "agahi_admin"
SESSION_HOURS = 12
MAX_FAILS = 5
FAIL_WINDOW_S = 300
_fails: dict[str, deque] = defaultdict(deque)


def _sign(msg: str) -> str:
    return hmac.new(settings.secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    """Session token = issued-at + signature."""
    ts = str(int(time.time()))
    return f"{ts}.{_sign('admin:' + ts)}"


def valid_token(token: str | None) -> bool:
    """Check signature and age."""
    if not token or "." not in token:
        return False
    ts, sig = token.split(".", 1)
    if not ts.isdigit() or time.time() - int(ts) > SESSION_HOURS * 3600:
        return False
    return hmac.compare_digest(sig, _sign("admin:" + ts))


def csrf_for(token: str) -> str:
    """CSRF token bound to the session token."""
    return _sign("csrf:" + token)[:32]


def check_password(password: str, ip: str) -> bool:
    """Constant-time compare with a per-IP failure limit. Raises 429 when locked."""
    q = _fails[ip]
    now = time.time()
    while q and now - q[0] > FAIL_WINDOW_S:
        q.popleft()
    if len(q) >= MAX_FAILS:
        raise ApiError(429, "too_many_attempts", "Too many failed logins. Wait 5 minutes.")
    ok = hmac.compare_digest(password.encode(), settings.admin_password.encode())
    if not ok:
        q.append(now)
    return ok


def require_admin(request: Request) -> str:
    """Dependency: returns the session token or raises 401; enforces CSRF on POST."""
    token = request.cookies.get(COOKIE)
    if not valid_token(token):
        raise ApiError(401, "not_logged_in", "Please log in to the admin dashboard.")
    if request.method == "POST":
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent, csrf_for(token)):
            raise ApiError(403, "csrf", "Missing or invalid CSRF token. Reload the page.")
    return token

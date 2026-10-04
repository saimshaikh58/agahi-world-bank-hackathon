"""The single HTTP client wrapper. Tests monkeypatch `get_json` / `post` to stay offline."""
from __future__ import annotations

import httpx

TIMEOUT_S = 5.0


def get_json(url: str, params: dict | None = None, timeout: float = TIMEOUT_S) -> dict:
    """GET and parse JSON; raises on any failure."""
    with httpx.Client(timeout=timeout) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.json()


def post(url: str, data: dict | None = None, json_body: dict | None = None, headers: dict | None = None,
         auth: tuple[str, str] | None = None, timeout: float = TIMEOUT_S) -> tuple[int, str]:
    """POST and return (status, text); raises on network failure."""
    with httpx.Client(timeout=timeout) as c:
        r = c.post(url, data=data, json=json_body, headers=headers, auth=auth)
        return r.status_code, r.text

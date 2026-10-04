"""Tiny in-process pub/sub for Server-Sent Events (thread-safe publish into asyncio queues)."""
from __future__ import annotations

import asyncio
import json
import threading

_subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
_lock = threading.Lock()
MAX_QUEUE = 200


def subscribe() -> asyncio.Queue:
    """Register a queue for the current event loop."""
    q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
    with _lock:
        _subs.append((asyncio.get_running_loop(), q))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a queue."""
    with _lock:
        _subs[:] = [s for s in _subs if s[1] is not q]


def publish(event: str, data: dict) -> None:
    """Send an event to all subscribers; never raises."""
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    with _lock:
        subs = list(_subs)
    for loop, q in subs:
        try:
            loop.call_soon_threadsafe(_put, q, payload)
        except RuntimeError:
            unsubscribe(q)


def _put(q: asyncio.Queue, payload: str) -> None:
    if not q.full():
        q.put_nowait(payload)

"""Progress events (streamed to the UI with server-sent events) and the global kill switch."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from typing import Any

from app.models import now_iso

_EVENTS: dict[str, list[dict[str, Any]]] = defaultdict(list)
_LOCK = threading.Lock()
KILL = threading.Event()


class Cancelled(RuntimeError):
    """Raised inside agents when the founder pressed the kill switch."""


def emit(run_id: str, kind: str, message: str, **data: Any) -> None:
    event = {"ts": now_iso(), "kind": kind, "message": message, **data}
    with _LOCK:
        _EVENTS[run_id].append(event)


def since(run_id: str, index: int) -> list[dict[str, Any]]:
    with _LOCK:
        return list(_EVENTS[run_id][index:])


def check_kill() -> None:
    if KILL.is_set():
        raise Cancelled("Kill switch is on: all agents stopped.")


def sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def wait_tick() -> None:
    time.sleep(0.3)

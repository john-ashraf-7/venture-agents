"""Decision log: one entry per agent action.

Required keys (organizers' format): timestamp, agent, action, sources, model, cost, approved_by.
Strategic decisions add: options_considered, initiated_by, chosen_by, recommendation, override,
override_reason, outcome.
"""
from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any, Optional

from app.config import outputs_dir, root_decision_log
from app.models import now_iso
from app.services import events

_LOCK = threading.Lock()
REQUIRED = ("timestamp", "agent", "action", "sources", "model", "cost", "approved_by")


def run_dir(run_id: str) -> Path:
    p = outputs_dir() / "runs" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path(run_id: str) -> Path:
    return run_dir(run_id) / "decision_log.json"


def read(run_id: str) -> list[dict[str, Any]]:
    p = log_path(run_id)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8") or "[]")


def append(run_id: str, agent: str, action: str, *, sources: Optional[list[str]] = None,
           model: Optional[str] = None, cost: float = 0.0, approved_by: Optional[str] = None,
           **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "timestamp": now_iso(),
        "agent": agent,
        "action": action,
        "sources": [s for s in (sources or []) if s],
        "model": model,
        "cost": round(float(cost), 6),
        "approved_by": approved_by,
        "run_id": run_id,
    }
    entry.update({k: v for k, v in extra.items()})
    with _LOCK:
        entries = read(run_id)
        entries.append(entry)
        log_path(run_id).write_text(json.dumps(entries, indent=1, default=str), encoding="utf-8")
    events.emit(run_id, "log", f"{agent}: {action}", entry=entry)
    return entry


def publish_to_root(run_id: str) -> Path:
    """Copy a run's decision log to the repo-root decision_log.json (the committed demo run)."""
    target = root_decision_log()
    data = log_path(run_id).read_text(encoding="utf-8")
    # write in place (the file may be a docker bind mount)
    with open(target, "w", encoding="utf-8") as f:
        f.write(data)
    return target


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)

"""Cost meter: tokens x reference price per model + wall-clock time, per run.

Local runs cost $0.00 in API fees. `ref_cost_usd` is what the same tokens would cost on a
hosted open-weight endpoint (reference prices in config/models.yaml, an ASSUMPTION).
"""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.config import outputs_dir
from app.models import now_iso

_LOCK = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": [], "started": time.time()})
_LAST_CALL: dict[str, dict[str, Any]] = {}


def record_call(run_id: Optional[str], role: str, model: Any, tokens_in: int, tokens_out: int, latency_s: float,
                cache_hit: bool = False, error: Optional[str] = None) -> dict[str, Any]:
    ref = (tokens_in * model.ref_in + tokens_out * model.ref_out) / 1_000_000
    row = {"ts": now_iso(), "role": role, "model": model.name, "family": model.family, "tokens_in": tokens_in,
           "tokens_out": tokens_out, "latency_s": round(latency_s, 3), "ref_cost_usd": round(ref, 6),
           "cost_usd": 0.0, "cache_hit": cache_hit, "error": error}
    with _LOCK:
        _RUNS[run_id or "_global"]["calls"].append(row)
        _LAST_CALL[run_id or "_global"] = row
        if run_id:
            with _calls_path(run_id).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
    return row


def _calls_path(run_id: str) -> Path:
    """Calls are also kept on disk so a later process (e.g. a founder decision via the CLI) sees the whole run."""
    p = outputs_dir() / "runs" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "llm_calls.jsonl"


def _load_calls(run_id: str) -> list[dict[str, Any]]:
    p = _calls_path(run_id)
    if p.exists():
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return list(_RUNS[run_id]["calls"])


def last_call(run_id: Optional[str]) -> dict[str, Any]:
    return _LAST_CALL.get(run_id or "_global", {})


def start(run_id: str) -> None:
    with _LOCK:
        _RUNS[run_id]["started"] = time.time()


def summary(run_id: str) -> dict[str, Any]:
    with _LOCK:
        calls = _load_calls(run_id)
        started = _RUNS[run_id]["started"]
    by_model: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0, "ref_cost_usd": 0.0})
    for c in calls:
        m = by_model[c["model"]]
        m["calls"] += 1
        m["tokens_in"] += c["tokens_in"]
        m["tokens_out"] += c["tokens_out"]
        m["ref_cost_usd"] += c["ref_cost_usd"]
    tin = sum(c["tokens_in"] for c in calls)
    tout = sum(c["tokens_out"] for c in calls)
    return {
        "run_id": run_id,
        "cost_usd": 0.0,
        "cost_note": "Local open-weight models: $0.00 API cost. Electricity not included.",
        "ref_cost_usd": round(sum(c["ref_cost_usd"] for c in calls), 6),
        "ref_cost_note": "ASSUMPTION: same tokens at hosted open-model reference prices (config/models.yaml).",
        "llm_calls": len(calls),
        "cache_hits": sum(1 for c in calls if c["cache_hit"]),
        "tokens_in": tin,
        "tokens_out": tout,
        "llm_seconds": round(sum(c["latency_s"] for c in calls), 1),
        # a later process (founder decision) did not see the run start, so it reports the span of the calls
        "wall_clock_s": round(_span_s(calls) if calls and started > _first_ts(calls) else time.time() - started, 1),
        "by_model": by_model,
    }


def _first_ts(calls: list[dict[str, Any]]) -> float:
    return datetime.fromisoformat(calls[0]["ts"].replace("Z", "+00:00")).timestamp() - calls[0]["latency_s"]


def _span_s(calls: list[dict[str, Any]]) -> float:
    """First call start to last call end (excludes time spent waiting for the founder)."""
    if not calls:
        return 0.0
    last = datetime.fromisoformat(calls[-1]["ts"].replace("Z", "+00:00")).timestamp()
    return last - _first_ts(calls)


def write(run_id: str, path: Any) -> dict[str, Any]:
    s = summary(run_id)
    path.write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s

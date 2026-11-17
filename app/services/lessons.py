"""Lessons log + shared memory with a relevance filter.

Failures and checker findings are appended to data/lessons.jsonl and read by later steps and runs.
Retrieval uses the `embed` model (nomic-embed-text via Ollama) and cosine similarity; only lessons
above a relevance threshold reach an agent. If embeddings are unavailable, keyword overlap is used.
(ChromaDB was replaced by this small SQLite/JSONL store: same behaviour, one less service.)
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

import httpx

from app.config import data_dir, env, load_yaml
from app.models import now_iso

THRESHOLD = 0.55


def _path():
    return data_dir() / "lessons.jsonl"


def add(run_id: str, kind: str, text: str) -> None:
    with open(_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_iso(), "run_id": run_id, "kind": kind, "text": text[:400]}) + "\n")


def all_lessons() -> list[dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _embed(texts: list[str]) -> Optional[list[list[float]]]:
    if env("SEARCH_MODE") == "fixtures":
        return None
    try:
        name = load_yaml("models.yaml")["models"]["embed"]["name"]
        r = httpx.post(f"{env('OLLAMA_URL', 'http://ollama:11434')}/api/embed", json={"model": name, "input": texts}, timeout=30)
        r.raise_for_status()
        return r.json()["embeddings"]
    except Exception:
        return None


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _overlap(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"\w{4,}", a.lower())), set(re.findall(r"\w{4,}", b.lower()))
    return len(wa & wb) / (len(wa | wb) or 1)


def relevant(query: str, k: int = 5) -> list[str]:
    lessons = all_lessons()[-200:]
    if not lessons:
        return []
    texts = [l["text"] for l in lessons]
    vecs = _embed([query] + texts)
    if vecs:
        scored = [(_cos(vecs[0], v), t) for v, t in zip(vecs[1:], texts)]
        thr = THRESHOLD
    else:
        scored = [(_overlap(query, t), t) for t in texts]
        thr = 0.08
    seen, out = set(), []
    for s, t in sorted(scored, reverse=True):
        if s >= thr and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= k:
            break
    return out

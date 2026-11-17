"""Reranker: orders search results by how well they fit a search PURPOSE (role `reranker`,
bge-reranker-v2-m3 cross-encoder by default; CPU unless the model's device says otherwise).

    rerank(purpose_text("demand", problem="late invoice payments"), results) -> results with "rerank_score"

Results are SearXNG result dicts (url, title, snippet, engines); they come back as new dicts, best first.
TODO(search): call this between SearXNG results and fetching (see docs/INTEGRATION_NOTES.md). Not wired yet.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from app import llm
from app.config import load_yaml

Scorer = Callable[[str, list[str]], list[float]]
_SCORER_OVERRIDE: Optional[Scorer] = None  # tests install a STUBBED scorer here


def set_scorer(fn: Optional[Scorer]) -> None:
    global _SCORER_OVERRIDE
    _SCORER_OVERRIDE = fn


def purpose_text(purpose: str, **fields: str) -> str:
    template = load_yaml("rerank_purposes.yaml")["purposes"][purpose]
    return template.format(**{k: (v or "").strip() for k, v in fields.items()})


def passage(r: dict[str, Any]) -> str:
    return f"{r.get('title') or ''}\n{r.get('snippet') or r.get('content') or ''}\n{r.get('url') or ''}".strip()


def _model_scorer(query: str, passages: list[str]) -> list[float]:
    from app.llm import local_transformers as lt
    spec = llm.resolve("reranker").model
    if os.environ.get("RERANKER_DEVICE"):
        spec.extra["device"] = os.environ["RERANKER_DEVICE"]
    return lt.rerank_scores(spec, query, passages)


def rerank(purpose: str, results: list[dict[str, Any]], *, top_k: Optional[int] = None,
           min_score: Optional[float] = None) -> list[dict[str, Any]]:
    """Score each result against the purpose text, return copies sorted best first with `rerank_score`."""
    if not results:
        return []
    scores = (_SCORER_OVERRIDE or _model_scorer)(purpose, [passage(r) for r in results])
    out = [{**r, "rerank_score": round(float(s), 4)} for r, s in zip(results, scores)]
    out.sort(key=lambda r: -r["rerank_score"])
    if min_score is not None:
        out = [r for r in out if r["rerank_score"] >= min_score]
    return out[:top_k] if top_k else out

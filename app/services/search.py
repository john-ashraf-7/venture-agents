"""Capped web search through self-hosted SearXNG, with an on-disk cache.

SEARCH_MODE=live        query SearXNG; on failure fall back to the cache, labeled "cached search from <time>"
SEARCH_MODE=cache_only  only the cache
SEARCH_MODE=fixtures    evals/fixtures/search/*.json (offline evals and tests)
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import httpx

from app.config import EVALS_DIR, data_dir, env
from app.models import now_iso


def _slug(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]


def _cache_path(query: str):
    d = data_dir() / "search_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{_slug(query)}.json"


def _fixture(query: str) -> dict[str, Any] | None:
    d = EVALS_DIR / "fixtures" / "search"
    p = d / f"{_slug(query)}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    default = d / "_default.json"
    if default.exists():
        return json.loads(default.read_text(encoding="utf-8"))
    return None


def search(query: str, n: int) -> dict[str, Any]:
    """Return {"query", "results": [{url,title,snippet}], "origin": live|cache|fixture|none, "note"}."""
    mode = env("SEARCH_MODE", "live")
    if mode == "fixtures":
        fx = _fixture(query)
        if fx:
            return {"query": query, "results": fx["results"][:n], "origin": "fixture",
                    "note": "fixture search results (evals/fixtures/search)"}
        return {"query": query, "results": [], "origin": "none", "note": "no fixture"}
    cache = _cache_path(query)
    if mode == "live":
        try:
            r = httpx.get(f"{env('SEARXNG_URL', 'http://searxng:8080')}/search",
                          params={"q": query, "format": "json", "language": "en"}, timeout=20)
            r.raise_for_status()
            body = r.json()
            results = [{"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("content", ""),
                        "engines": x.get("engines", [])}
                       for x in body.get("results", []) if re.match(r"^https?://", x.get("url", ""))]
            meta = {"engines": sorted({e for x in results for e in x["engines"]}),
                    "unresponsive": [list(u) for u in body.get("unresponsive_engines", [])]}
            if results:
                payload = {"query": query, "results": results[:10], "cached_at": now_iso(), **meta}
                cache.write_text(json.dumps(payload), encoding="utf-8")
                return {"query": query, "results": results[:n], "origin": "live", "note": "live search (SearXNG)", **meta}
        except (httpx.HTTPError, ValueError):
            pass
    if cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
        return {"query": query, "results": payload["results"][:n], "origin": "cache",
                "note": f"cached search from {payload.get('cached_at')}"}
    return {"query": query, "results": [], "origin": "none", "note": "search unavailable and no cache"}

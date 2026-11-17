"""Capped web search through self-hosted SearXNG, with an on-disk cache.

SEARCH_MODE=live        fresh cache (24h, keyed by query + engines) first, else query SearXNG with the engines routed
                        for the purpose (config/search.yaml), one query at a time with a short delay; on failure
                        fall back to the cache, labeled "cached search from <time>"
SEARCH_MODE=cache_only  only the cache
SEARCH_MODE=fixtures    evals/fixtures/search/*.json (offline evals and tests)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import EVALS_DIR, data_dir, env, load_yaml
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


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def filter_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe URLs, keep at most max_per_domain per domain, move low-priority domains to the end."""
    f = load_yaml("search_filters.yaml")
    low = tuple(f.get("low_priority_domains", []))
    per: dict[str, int] = {}
    seen: set[str] = set()
    keep, tail = [], []
    for r in results:
        u = r["url"].split("#")[0]
        d = _domain(u)
        if u in seen or per.get(d, 0) >= f.get("max_per_domain", 2):
            continue
        seen.add(u)
        per[d] = per.get(d, 0) + 1
        (tail if d.endswith(low) else keep).append(r)
    return keep + tail


_LAST_LIVE = [0.0]


def search(query: str, n: int, purpose: str = "competitors") -> dict[str, Any]:
    """Return {"query", "results": [{url,title,snippet,engines}], "origin": live|cache|fixture|none, "note",
    "engines", "unresponsive"}. Engines come from config/search.yaml by purpose; fresh cache is used first."""
    mode = env("SEARCH_MODE", "live")
    if mode == "fixtures":
        fx = _fixture(query)
        if fx:
            return {"query": query, "results": fx["results"][:n], "origin": "fixture",
                    "note": "fixture search results (evals/fixtures/search)", "engines": [], "unresponsive": []}
        return {"query": query, "results": [], "origin": "none", "note": "no fixture", "engines": [], "unresponsive": []}
    cfg = load_yaml("search.yaml")
    engines = cfg["routes"].get(purpose, cfg["routes"]["competitors"])
    cache = _cache_path(query + "|" + ",".join(engines))
    cached = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    fresh = cached and time.time() - cached.get("cached_ts", 0) < float(cfg.get("cache_ttl_hours", 24)) * 3600
    if cached and (fresh or mode == "cache_only"):
        return _from_cache(query, cached, n)
    if mode == "live":
        wait = float(cfg.get("delay_between_queries_s", 1.0)) - (time.time() - _LAST_LIVE[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = httpx.get(f"{env('SEARXNG_URL', 'http://searxng:8080')}/search",
                          params={"q": query, "format": "json", "language": "en", "engines": ",".join(engines)}, timeout=20)
            _LAST_LIVE[0] = time.time()
            r.raise_for_status()
            body = r.json()
            results = filter_results([{"url": x.get("url", ""), "title": x.get("title", ""), "snippet": x.get("content", ""),
                                       "engines": x.get("engines", [])}
                                      for x in body.get("results", []) if re.match(r"^https?://", x.get("url", ""))])
            meta = {"engines": sorted({e for x in results for e in x["engines"]}),
                    "unresponsive": [list(u) for u in body.get("unresponsive_engines", [])]}
            if results:
                payload = {"query": query, "results": results[:12], "cached_at": now_iso(), "cached_ts": time.time(), **meta}
                cache.write_text(json.dumps(payload), encoding="utf-8")
                return {"query": query, "results": results[:n], "origin": "live", "note": "live search (SearXNG)", **meta}
            if cached:
                return {**_from_cache(query, cached, n), "unresponsive": meta["unresponsive"]}
            return {"query": query, "results": [], "origin": "none", "note": "no live results and no cache", **meta}
        except (httpx.HTTPError, ValueError):
            pass
    if cached:
        return _from_cache(query, cached, n)
    return {"query": query, "results": [], "origin": "none", "note": "search unavailable and no cache",
            "engines": [], "unresponsive": []}


def _from_cache(query: str, payload: dict[str, Any], n: int) -> dict[str, Any]:
    return {"query": query, "results": payload["results"][:n], "origin": "cache",
            "note": f"cached search from {payload.get('cached_at')}", "engines": payload.get("engines", []),
            "unresponsive": payload.get("unresponsive", [])}

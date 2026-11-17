"""OPTIONAL search provider: Tavily (https://tavily.com), a hosted search API built for agents.

SEARCH_PROVIDER=auto (default) uses Tavily only when TAVILY_API_KEY (the founder's own key, free tier about
1,000 credits a month) is set; SEARCH_PROVIDER=tavily does the same; SEARCH_PROVIDER=searxng never calls it.
With no key, or when Tavily errors or is out of credits, app.services.search.search falls back to self-hosted
SearXNG for that query and logs why. Each live query is one "basic" search (1 credit). Results go through the
same 24h on-disk cache and the same noise filter (filter_results) as SearXNG, and come back in the same shape.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.config import env, load_yaml
from app.models import now_iso

API_URL = "https://api.tavily.com/search"


def enabled() -> bool:
    return env("SEARCH_PROVIDER", "auto").lower() in ("auto", "tavily") and bool(env("TAVILY_API_KEY"))


def _options(purpose: str, n: int) -> dict[str, Any]:
    opts: dict[str, Any] = {"search_depth": "basic", "topic": "general", "max_results": max(1, min(n, 20)),
                            "include_answer": False, "include_raw_content": False}
    if purpose == "demand":
        # demand signals only count from community sites, so ask Tavily for those directly
        domains = load_yaml("gate_definitions.yaml")["desk_gate"]["community_domains"]
        opts["include_domains"] = sorted({d.split("/")[0] for d in domains})
    return opts


def search(query: str, n: int, purpose: str = "competitors") -> dict[str, Any]:
    from app.services.search import _cache_path, _from_cache, filter_results  # avoid a circular import

    mode = env("SEARCH_MODE", "live")
    cfg = load_yaml("search.yaml")
    cache = _cache_path(query + "|tavily|" + purpose)
    cached = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    fresh = cached and time.time() - cached.get("cached_ts", 0) < float(cfg.get("cache_ttl_hours", 24)) * 3600
    if cached and (fresh or mode == "cache_only"):
        return _from_cache(query, cached, n)
    if mode == "live":
        try:
            r = httpx.post(API_URL, json={"query": query, **_options(purpose, max(n, 12))},
                           headers={"Authorization": f"Bearer {env('TAVILY_API_KEY')}"}, timeout=30)
            r.raise_for_status()
            body = r.json()
            results = filter_results([{"url": x.get("url", ""), "title": x.get("title", ""),
                                       "snippet": x.get("content", ""), "engines": ["tavily"]}
                                      for x in body.get("results", []) if x.get("url", "").startswith("http")])
            if results:
                payload = {"query": query, "results": results[:12], "cached_at": now_iso(), "cached_ts": time.time(),
                           "engines": ["tavily"], "unresponsive": []}
                cache.write_text(json.dumps(payload), encoding="utf-8")
                return {"query": query, "results": results[:n], "origin": "live", "note": "live search (Tavily)",
                        "engines": ["tavily"], "unresponsive": []}
            if cached:
                return _from_cache(query, cached, n)
            return {"query": query, "results": [], "origin": "none", "note": "no live results and no cache (Tavily)",
                    "engines": ["tavily"], "unresponsive": []}
        except (httpx.HTTPError, ValueError) as e:
            # never echo the request (it carries the key); status code only
            status = getattr(getattr(e, "response", None), "status_code", None)
            reason = {401: "invalid key", 429: "rate limited", 432: "out of credits", 433: "out of credits"}.get(status, "")
            unresponsive = [["tavily", f"HTTP {status} {reason}".strip() if status else type(e).__name__]]
            if cached:
                return {**_from_cache(query, cached, n), "unresponsive": unresponsive}
            return {"query": query, "results": [], "origin": "none", "note": "Tavily unavailable and no cache",
                    "engines": [], "unresponsive": unresponsive}
    if cached:
        return _from_cache(query, cached, n)
    return {"query": query, "results": [], "origin": "none", "note": "search unavailable and no cache",
            "engines": [], "unresponsive": []}

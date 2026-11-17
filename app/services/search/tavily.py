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
from typing import Any, Optional

import httpx

from app.config import env, load_yaml
from app.models import now_iso

API_URL = "https://api.tavily.com/search"


def enabled() -> bool:
    return env("SEARCH_PROVIDER", "auto").lower() in ("auto", "tavily") and bool(env("TAVILY_API_KEY"))


def settings() -> dict[str, Any]:
    return load_yaml("community.yaml").get("tavily", {}) or {}


_SPENT: dict[str, int] = {}


def over_budget(run_id: Optional[str]) -> bool:
    """Per-run credit budget (config/community.yaml tavily.max_searches_per_run); past it, SearXNG is used."""
    return bool(run_id) and _SPENT.get(run_id, 0) >= int(settings().get("max_searches_per_run", 12))


def _spend(run_id: Optional[str]) -> None:
    if run_id:
        _SPENT[run_id] = _SPENT.get(run_id, 0) + 1


def _options(purpose: str, n: int) -> dict[str, Any]:
    opts: dict[str, Any] = {"search_depth": "basic", "topic": "general", "max_results": max(1, min(n, 20)),
                            "include_answer": False, "include_raw_content": False}
    if purpose == "demand":
        # demand signals only count from community sites, so ask Tavily for those directly, with the page text:
        # community sites (Reddit above all) refuse our own fetches, but Tavily's index often has the thread.
        # Quotes must then be exact substrings of that raw content (checked in code).
        t = settings()
        opts["include_domains"] = sorted({d.split("/")[0] for d in t.get("demand_include_domains", [])
                                          + t.get("extra_community_domains", [])})
        opts["include_raw_content"] = True
    else:  # competitors and pricing: no domain filter, but no SEO template galleries / content farms
        low = load_yaml("search_filters.yaml").get("low_priority_domains", [])
        if low:
            opts["exclude_domains"] = list(low)
    return opts


def search(query: str, n: int, purpose: str = "competitors", run_id: Optional[str] = None) -> dict[str, Any]:
    from app.services.search import _cache_path, _from_cache, filter_results  # avoid a circular import

    mode = env("SEARCH_MODE", "live")
    cfg = load_yaml("search.yaml")
    cache = _cache_path(query + "|tavily|" + purpose)
    cached = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else None
    fresh = cached and time.time() - cached.get("cached_ts", 0) < float(cfg.get("cache_ttl_hours", 24)) * 3600
    if cached and (fresh or mode == "cache_only"):
        return _from_cache(query, cached, n)
    if mode == "live" and over_budget(run_id):
        cap = settings().get("max_searches_per_run", 12)
        return {"query": query, "results": [], "origin": "none", "note": f"Tavily per-run budget of {cap} searches used up",
                "engines": [], "unresponsive": [["tavily", f"per-run budget of {cap} searches used up"]]}
    if mode == "live":
        _spend(run_id)
        try:
            r = httpx.post(API_URL, json={"query": query, **_options(purpose, max(n, 12))},
                           headers={"Authorization": f"Bearer {env('TAVILY_API_KEY')}"}, timeout=30)
            r.raise_for_status()
            body = r.json()
            results = filter_results([{"url": x.get("url", ""), "title": x.get("title", ""),
                                       "snippet": x.get("content", ""), "engines": ["tavily"],
                                       "raw_content": (x.get("raw_content") or "")[:20000]}
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


EXTRACT_URL = "https://api.tavily.com/extract"


def extract(urls: list[str]) -> dict[str, str]:
    """Page text for URLs we could not fetch ourselves (bot walls, 403s), via Tavily's Extract API.
    One "basic" extract costs 1 credit per 5 successful URLs. Returns {url: raw text}; cached 24h per URL.
    The text is still untrusted page data: it goes to the isolated reader, and quotes must match it exactly."""
    from app.services.search import _cache_path  # avoid a circular import

    out: dict[str, str] = {}
    todo = []
    for u in urls:
        p = _cache_path("tavily-extract|" + u)
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - d.get("ts", 0) < 24 * 3600:
                if d.get("text"):
                    out[u] = d["text"]
                continue
        todo.append(u)
    if not todo or not enabled() or env("SEARCH_MODE", "live") != "live":
        return out
    try:
        r = httpx.post(EXTRACT_URL, json={"urls": todo[:20], "extract_depth": "basic", "include_images": False},
                       headers={"Authorization": f"Bearer {env('TAVILY_API_KEY')}"}, timeout=40)
        r.raise_for_status()
        got = {x.get("url", ""): x.get("raw_content") or "" for x in r.json().get("results", [])}
    except (httpx.HTTPError, ValueError):
        return out  # status only matters to the caller as "no text"; never echo the request (it carries the key)
    for u in todo[:20]:
        text = got.get(u, "")
        _cache_path("tavily-extract|" + u).write_text(json.dumps({"url": u, "text": text, "ts": time.time()}), encoding="utf-8")
        if text:
            out[u] = text
    return out

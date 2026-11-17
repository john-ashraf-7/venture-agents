"""Community posts for demand evidence, from official APIs (config/community.yaml).

Providers, each optional and free: Hacker News (Algolia, no key), Stack Exchange (STACKEXCHANGE_KEY optional),
Reddit (official OAuth API, only when REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are set; reddit.com HTML is never
fetched). Every provider call has a per-run budget, a 24 h disk cache under DATA_DIR/community_cache, and a
decision-log entry. Post text and dates are copied from the API response (HTML stripped), never from a model.
In SEARCH_MODE=fixtures nothing is called.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx
from pydantic import BaseModel

from app.config import data_dir, env, load_yaml
from app.services import decision_log


class CommunityPost(BaseModel):
    source: str                 # provider: hackernews | stackexchange | reddit
    url: str
    author_handle_hash: str     # sha256 of the handle, truncated; the handle itself is not stored
    created_at: str             # ISO date (YYYY-MM-DD)
    text: str                   # exact text from the API, HTML stripped
    score: int = 0
    thread_title: str = ""


def config() -> dict[str, Any]:
    return load_yaml("community.yaml")


def hash_handle(handle: Optional[str]) -> str:
    return hashlib.sha256((handle or "").encode("utf-8")).hexdigest()[:12] if handle else ""


def strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<\s*(br|/p|p|/li|/pre|/blockquote)\b[^>]*>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def iso_date(ts: Any) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return str(ts or "")[:10]


def mentions(text: str, query: str) -> bool:
    """Keyword APIs match loosely (typo tolerance, single words): keep a post only when it names a query word
    (hyphens and spaces dropped, 4-letter stems), e.g. 'todo' for 'to-do list'."""
    squash = re.sub(r"[^a-z0-9]", "", (text or "").lower())
    words = [w.replace("-", "") for w in re.findall(r"[a-z][a-z-]+", query.lower())]
    words = [w for w in words if len(w) >= 4]
    return any(w[:max(4, len(w) - 2)] in squash for w in words) if words else True


# ------------------------------------------------------------------ cache and budget
_BUDGET: dict[tuple[str, str], int] = {}
_THROTTLED: set[tuple[str, str]] = set()
_LOCK = threading.Lock()


def _cache_file(provider: str, key: str):
    d = data_dir() / "community_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{provider}_{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"


def _spend(run_id: Optional[str], provider: str, budget: int) -> bool:
    with _LOCK:
        k = (run_id or "-", provider)
        if _BUDGET.get(k, 0) >= budget:
            return False
        _BUDGET[k] = _BUDGET.get(k, 0) + 1
        return True


def _cached_call(run_id: Optional[str], provider: str, query: str, key: str,
                 fetch: Callable[[], list[CommunityPost]]) -> list[CommunityPost]:
    cfg = config()
    pcfg = cfg["providers"][provider]
    f = _cache_file(provider, key)
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) < cfg.get("cache_hours", 24) * 3600:
            posts = [CommunityPost(**p) for p in data["posts"]]
            if run_id:
                decision_log.append(run_id, "community", "community_search", sources=[p.url for p in posts], model=None,
                                    provider=provider, query=query, origin="cache", endpoint=key.split("|")[0])
            return posts
    if not _spend(run_id, provider, int(pcfg.get("budget", 4))):
        if run_id:
            decision_log.append(run_id, "community", "community_search_skipped", sources=[], model=None,
                                provider=provider, query=query,
                                reason="provider throttled earlier this run (429/quota)" if (run_id or "-", provider) in _THROTTLED
                                else "per-run call budget used up")
        return []
    try:
        posts = fetch()
    except (httpx.HTTPError, ValueError, KeyError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (400, 429, 502, 503):  # Stack Exchange throttle_violation / quota: stop calling it this run
            with _LOCK:
                _BUDGET[(run_id or "-", provider)] = 10 ** 6
                _THROTTLED.add((run_id or "-", provider))
        if run_id:
            decision_log.append(run_id, "community", "community_search", sources=[], model=None, provider=provider,
                                query=query, origin="live", error=f"{type(e).__name__}: {str(e)[:150]}")
        return []
    f.write_text(json.dumps({"ts": time.time(), "posts": [p.model_dump() for p in posts]}), encoding="utf-8")
    if run_id:
        decision_log.append(run_id, "community", "community_search", sources=[p.url for p in posts], model=None,
                            provider=provider, query=query, origin="live", endpoint=key.split("|")[0])
    return posts


def _client() -> httpx.Client:
    cfg = config()
    ua = cfg["providers"].get("reddit", {}).get("user_agent", "venture-builder-research/0.1")
    return httpx.Client(timeout=cfg.get("timeout_s", 10), headers={"User-Agent": ua}, follow_redirects=True)


# ------------------------------------------------------------------ providers
def hackernews(query: str, limit: int, run_id: Optional[str] = None, context: str = "") -> list[CommunityPost]:
    pcfg = config()["providers"]["hackernews"]
    out: list[CommunityPost] = []
    for endpoint in pcfg.get("endpoints", ["search"]):
        def fetch(endpoint: str = endpoint) -> list[CommunityPost]:
            with _client() as c:
                r = c.get(f"https://hn.algolia.com/api/v1/{endpoint}",
                          params={"query": query, "tags": pcfg.get("tags", "(story,comment)"), "hitsPerPage": limit})
                r.raise_for_status()
                posts = []
                for h in r.json().get("hits", []):
                    title = h.get("title") or h.get("story_title") or ""
                    text = strip_html(h.get("comment_text") or h.get("story_text") or "")
                    if not text or not mentions(text + " " + title, query):
                        continue
                    posts.append(CommunityPost(
                        source="hackernews", url=f"https://news.ycombinator.com/item?id={h['objectID']}",
                        author_handle_hash=hash_handle(h.get("author")), created_at=iso_date(h.get("created_at_i") or h.get("created_at")),
                        text=text, score=int(h.get("points") or 0), thread_title=title))
                return posts
        out += _cached_call(run_id, "hackernews", query, f"{endpoint}|{query}|{limit}", fetch)
    return out


def pullpush(query: str, limit: int, run_id: Optional[str] = None, context: str = "") -> list[CommunityPost]:
    """Reddit posts and comments from the PullPush archive API (no key, no scraping of reddit.com).
    The text, author and date come from the archive's copy of the Reddit post; the URL points to Reddit."""
    pcfg = config()["providers"].get("pullpush", {})
    out: list[CommunityPost] = []
    for kind in pcfg.get("kinds", ["submission", "comment"]):
        def fetch(kind: str = kind) -> list[CommunityPost]:
            with _client() as c:
                r = c.get(f"https://api.pullpush.io/reddit/search/{kind}/", params={"q": f'"{query}"' if len(query.split()) > 1 else query, "size": limit,
                                  "sort_type": "score", "sort": "desc"})  # exact phrase: unquoted search is off-topic
                r.raise_for_status()
                posts = []
                for h in r.json().get("data", []) or []:
                    title = h.get("title") or h.get("link_title") or ""
                    text = strip_html(h.get("selftext") or h.get("body") or "")
                    if kind == "submission":
                        text = (title + "\n" + text).strip()
                    if not text or text in ("[removed]", "[deleted]") or not mentions(text + " " + title, query):
                        continue
                    link = h.get("permalink") or ""
                    url = ("https://www.reddit.com" + link) if link.startswith("/") else (h.get("url") or "")
                    if not url.startswith("https://www.reddit.com/"):
                        continue
                    posts.append(CommunityPost(
                        source="reddit (PullPush archive)", url=url, author_handle_hash=hash_handle(h.get("author")),
                        created_at=iso_date(h.get("created_utc")), text=text[:4000], score=int(h.get("score") or 0),
                        thread_title=title))
                return posts
        out += _cached_call(run_id, "pullpush", query, f"{kind}|{query}|{limit}", fetch)
    return out


def appstore(query: str, limit: int, run_id: Optional[str] = None, context: str = "") -> list[CommunityPost]:
    """Competitor app reviews from Apple's public iTunes Search API and customer-review feeds (no key).
    Buyers complaining about, or wishing for more from, the tools they already use: dated, first-hand text.
    Low-rated reviews (<= max_rating) only; the demand classifier still judges each one."""
    pcfg = config()["providers"].get("appstore", {})
    term = (query or context).strip()  # the problem phrase; the joined context is too long for app search

    def fetch() -> list[CommunityPost]:
        posts: list[CommunityPost] = []
        with _client() as c:
            r = c.get("https://itunes.apple.com/search", params={"term": term, "entity": "software",
                                                                 "limit": pcfg.get("apps", 3), "country": pcfg.get("country", "us")})
            r.raise_for_status()
            for app in r.json().get("results", []):
                aid, name = app.get("trackId"), app.get("trackName", "")
                rr = c.get(f"https://itunes.apple.com/{pcfg.get('country', 'us')}/rss/customerreviews/id={aid}/sortBy=mostRecent/json")
                if rr.status_code != 200:
                    continue
                entries = (rr.json().get("feed") or {}).get("entry") or []
                for e in entries if isinstance(entries, list) else [entries]:
                    lab = lambda k: (e.get(k) or {}).get("label", "") if isinstance(e.get(k), dict) else ""
                    try:
                        rating = int(lab("im:rating") or 5)
                    except ValueError:
                        rating = 5
                    text = (lab("title") + "\n" + lab("content")).strip()
                    if rating > int(pcfg.get("max_rating", 3)) or not text:
                        continue
                    posts.append(CommunityPost(
                        source=f"app store review ({name[:40]})", url=f"https://apps.apple.com/us/app/id{aid}#review-{lab('id')}",
                        author_handle_hash=hash_handle((e.get("author") or {}).get("name", {}).get("label") if isinstance(e.get("author"), dict) else ""),
                        created_at=(lab("updated") or "")[:10], text=text[:3000], score=rating, thread_title=f"Review of {name}"))
                    if len(posts) >= limit:
                        return posts
        return posts
    return _cached_call(run_id, "appstore", term, f"{term}|{limit}", fetch)


def stackexchange_sites(context: str) -> list[str]:
    """`always` sites (softwarerecs) plus every site whose words appear in the brief context; fallback otherwise."""
    pcfg = config()["providers"]["stackexchange"]
    ctx = (context or "").lower()
    picked = [s for s, words in (pcfg.get("sites") or {}).items() if any(w in ctx for w in words or [])]
    return list(dict.fromkeys(list(pcfg.get("always", [])) + (picked or list(pcfg.get("fallback_sites", [])))))


def stackexchange(query: str, limit: int, run_id: Optional[str] = None, context: str = "") -> list[CommunityPost]:
    out: list[CommunityPost] = []
    for site in stackexchange_sites(context or query):
        def fetch(site: str = site) -> list[CommunityPost]:
            params = {"q": query, "site": site, "order": "desc", "sort": "relevance", "filter": "withbody",
                      "pagesize": limit}
            if env("STACKEXCHANGE_KEY"):
                params["key"] = env("STACKEXCHANGE_KEY")
            with _client() as c:
                r = c.get("https://api.stackexchange.com/2.3/search/advanced", params=params)
                r.raise_for_status()
                posts = []
                for it in r.json().get("items", []):
                    text = strip_html(it.get("body", ""))
                    if not text:
                        continue
                    posts.append(CommunityPost(
                        source="stackexchange", url=it["link"], author_handle_hash=hash_handle((it.get("owner") or {}).get("display_name")),
                        created_at=iso_date(it.get("creation_date")), text=text, score=int(it.get("score") or 0),
                        thread_title=htmllib.unescape(it.get("title", ""))))
                return posts
        out += _cached_call(run_id, "stackexchange", query, f"{site}|{query}|{limit}", fetch)
    return out


def reddit_enabled() -> bool:
    return bool(env("REDDIT_CLIENT_ID") and env("REDDIT_CLIENT_SECRET"))


def reddit(query: str, limit: int, run_id: Optional[str] = None, context: str = "") -> list[CommunityPost]:
    """Official API only (client-credentials OAuth). Without credentials Reddit is skipped entirely."""
    if not reddit_enabled():
        return []

    def fetch() -> list[CommunityPost]:
        with _client() as c:
            tok = c.post("https://www.reddit.com/api/v1/access_token", data={"grant_type": "client_credentials"},
                         auth=(env("REDDIT_CLIENT_ID"), env("REDDIT_CLIENT_SECRET")))
            tok.raise_for_status()
            r = c.get("https://oauth.reddit.com/search", params={"q": query, "limit": limit, "sort": "relevance",
                                                                  "t": "year", "type": "link", "raw_json": 1},
                      headers={"Authorization": f"bearer {tok.json()['access_token']}"})
            r.raise_for_status()
            posts = []
            for ch in r.json().get("data", {}).get("children", []):
                d = ch.get("data", {})
                text = strip_html(d.get("selftext_html") or "") or (d.get("selftext") or "").strip()
                if not text:
                    continue
                posts.append(CommunityPost(
                    source="reddit", url="https://www.reddit.com" + d.get("permalink", ""), author_handle_hash=hash_handle(d.get("author")),
                    created_at=iso_date(d.get("created_utc")), text=text, score=int(d.get("score") or 0),
                    thread_title=d.get("title", "")))
            return posts
    return _cached_call(run_id, "reddit", query, f"search|{query}|{limit}", fetch)


PROVIDERS: dict[str, Callable[..., list[CommunityPost]]] = {"pullpush": pullpush, "appstore": appstore, "hackernews": hackernews,
                                                           "stackexchange": stackexchange, "reddit": reddit}


def search_community(problem_terms: list[str], audience: str, limit: int, run_id: Optional[str] = None,
                     context: str = "") -> list[CommunityPost]:
    """Posts from every enabled provider for the problem phrases (the audience is not added to the API query:
    it narrows keyword search too far; the demand classifier judges relevance). Deduplicated by URL, interleaved
    across providers so one provider cannot fill the list, at most `limit` posts."""
    cfg = config()
    if not cfg.get("enabled", True) or env("SEARCH_MODE", "live") != "live":
        return []
    terms = [t.strip() for t in problem_terms if t and t.strip()][: cfg.get("max_queries", 3)]
    generic = re.match(r"^(everyone|everybody|anyone|anybody|people|users)\b", (audience or "").strip(), re.I)
    per = cfg.get("per_query_limit", 8)
    by_provider: dict[str, list[CommunityPost]] = {}
    for name, fn in PROVIDERS.items():
        if not cfg["providers"].get(name, {}).get("enabled", False):
            continue
        qs = list(terms)
        if name == "hackernews" and cfg["providers"][name].get("audience_query") and audience and not generic and terms:
            qs.insert(1, f"{audience} {terms[0]}")
        for t in qs:
            by_provider.setdefault(name, []).extend(fn(t, per, run_id, context=" ".join([*terms, audience, context])))
    out: list[CommunityPost] = []
    seen: set[str] = set()
    lists = list(by_provider.values())
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l) and l[i].url not in seen and len(out) < limit:
                seen.add(l[i].url)
                out.append(l[i])
    return out

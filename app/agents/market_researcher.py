"""Market Researcher: capped search -> isolated page reader -> claim extraction (atomic, quoted)."""
from __future__ import annotations

import re
from typing import Any

from app import llm
from app.agents import base
from app.config import caps
from app.models import Brief, ClaimList, PageExtract, SearchTerms, now_iso
from app.services import decision_log, events, reader, search
from app.services.search import queries

SKIP_HOSTS = re.compile(r"(youtube\.com|facebook\.com|instagram\.com|tiktok\.com|x\.com|twitter\.com|linkedin\.com/in/|\.pdf$)", re.I)


def plan_queries(run_id: str, terms: SearchTerms, idea: str, purposes: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Build queries in code for each purpose ({purpose: competitor name or ''}), lint them, log rejections."""
    c = caps()
    limits = {"demand": c["demand_queries"], "competitors": c["competitor_queries"], "pricing": c["pricing_queries"],
              "pricing_fallback": 1, "alternatives": 1}
    planned = []
    for purpose, competitor in (purposes or {"demand": "", "competitors": ""}).items():
        for q in queries.build(terms, purpose, competitor=competitor, limit=limits[purpose]):
            why = queries.lint(q, idea)
            if why:
                decision_log.append(run_id, "market_researcher", "query_rejected", query=q, purpose=purpose, reason=why)
                continue
            planned.append((purpose, q))
    return planned


POOL_SIZE = 12
SNIPPETS_PER_PURPOSE = 3
MIN_SNIPPET = 80


def gather(run_id: str, planned: list[tuple[str, str]], skip: set[str] | None = None) -> dict[str, Any]:
    """Search each planned query, then per purpose: a pool of up to 12 candidate URLs, fetched until max_pages
    pass the quality check; failures are logged with a reason and replaced by the next candidate. Search
    snippets of failed or empty pages are kept as snippet-only pages (their claims are PARTIAL, never counted)."""
    c = caps()
    skip = set(skip or ())
    searches: list[dict[str, Any]] = []
    for purpose, q in planned:
        res = {**search.search(q, c["results_per_query"], purpose), "purpose": purpose}
        searches.append(res)
        decision_log.append(run_id, "market_researcher", "web_search", sources=[r["url"] for r in res["results"]],
                            model=None, query=q, purpose=purpose, origin=res["origin"], note=res["note"],
                            engines=res.get("engines", []), unresponsive=res.get("unresponsive", []))
        events.emit(run_id, "step", f"search '{q}' -> {len(res['results'])} results ({res['note']})")
    pages: list[dict[str, Any]] = []
    # competitor/pricing purposes first: a URL is read once, and only competitor-purpose pages may yield a
    # paying competitor, while demand signals depend on the site and the quote, not on the purpose
    for purpose in sorted(dict.fromkeys(s["purpose"] for s in searches), key=lambda x: x == "demand"):
        lists = [s["results"] for s in searches if s["purpose"] == purpose]
        pool: list[str] = []
        snippets: dict[str, str] = {}
        for i in range(max((len(l) for l in lists), default=0)):  # round-robin so one query cannot fill the pool
            for l in lists:
                if i < len(l):
                    u = l[i]["url"]
                    snippets.setdefault(u, f'{l[i].get("title", "")}\n{l[i].get("snippet", "")}'.strip())
                    if len(pool) < POOL_SIZE and u not in pool and u not in skip and not SKIP_HOSTS.search(u):
                        pool.append(u)
        events.check_kill()
        fetched = reader.fetch_many(pool, c["page_chars"], want=c["max_pages"])
        fallback: list[str] = []
        for page in fetched:
            u = page["url"]
            skip.add(u)
            if not page["ok"]:
                decision_log.append(run_id, "page_reader", "fetch_rejected", sources=[u], purpose=purpose, reason=page["reason"])
                fallback.append(u)
                continue
            try:
                extract = reader.read(u, page["text"], run_id=run_id)
            except llm.LLMError as e:
                decision_log.append(run_id, "page_reader", "read_failed", sources=[u], model=e.model, reason=e.detail[:200])
                fallback.append(u)
                continue
            last = __import__("app.services.cost", fromlist=["last_call"]).last_call(run_id)
            decision_log.append(run_id, "page_reader", "read_page_isolated", sources=[u], model=llm.model_name("page_reader"),
                                purpose=purpose, tokens_in=last.get("tokens_in"), tokens_out=last.get("tokens_out"),
                                text_chars=len(page["text"]), origin=page["origin"],
                                structured_prices=page.get("structured_prices", []))
            events.emit(run_id, "step", f"read {u} -> {extract.page_kind}" + (f", price {extract.price_text}" if extract.price_text else ""))
            ex = extract.model_dump()
            if not (ex["problem_statements"] or ex["price_text"] or ex["product_name"] or ex["features"]):
                fallback.append(u)
            pages.append({**page, "purpose": purpose, "extract": ex})
        # snippet fallback: the search engine's own text for pages that failed or gave no target fields
        for u in [u for u in fallback if len(snippets.get(u, "")) >= MIN_SNIPPET][:SNIPPETS_PER_PURPOSE]:
            pages.append(snippet_page(u, snippets[u], purpose))
            decision_log.append(run_id, "market_researcher", "snippet_fallback", sources=[u], purpose=purpose)
    return {"searches": searches, "pages": pages}


def snippet_page(url: str, text: str, purpose: str) -> dict[str, Any]:
    """A search-result snippet used as evidence text. No LLM read; claims from it are PARTIAL, 'snippet only'."""
    return {"url": url, "text": text, "retrieved_at": now_iso(), "origin": "search-snippet", "ok": True, "purpose": purpose,
            "snippet_only": True, "structured_prices": [],
            "extract": {"page_kind": "other", "snippet": text, "product_name": None, "price_text": None,
                        "has_public_price": False, "features": [], "problem_statements": [], "audience": None}}


def is_snippet(page: dict[str, Any]) -> bool:
    return bool(page.get("snippet_only"))


def extract_claims(run_id: str, brief: Brief, pages: list[dict[str, Any]]) -> ClaimList:
    if not pages:
        return ClaimList(claims=[])
    compact = [{"url": p["url"], "retrieved_at": p["retrieved_at"], "fields": p["extract"]} for p in pages]
    return base.run(run_id, "claim_extractor", "claim_extractor", "extract_atomic_claims", ClaimList,
                    {"idea": brief.idea, "target_market": brief.target_market, "page_extracts": compact},
                    sources=[p["url"] for p in pages],
                    instructions="Write atomic claims (one fact each) ONLY from these page extracts. Types: "
                                 "demand_signal (a person describing this problem, with date if known), paying_competitor "
                                 "(a product with a visible price), competitor, trend, market_size, compliance, other. "
                                 "source_quote must be words copied exactly from the extract fields of that URL.")


def normalize(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def quote_in_source(quote: str, text: str) -> bool:
    q = normalize(quote)
    if len(q) < 4:
        return False
    return q in normalize(text)


def page_extract(p: dict[str, Any]) -> PageExtract:
    return PageExtract.model_validate(p["extract"])

"""Market Researcher: capped search -> isolated page reader -> claim extraction (atomic, quoted)."""
from __future__ import annotations

import re
from typing import Any

from app import llm
from app.agents import base
from app.config import caps
from app.models import Brief, ClaimList, PageExtract
from app.services import decision_log, events, reader, search

SKIP_HOSTS = re.compile(r"(youtube\.com|facebook\.com|instagram\.com|tiktok\.com|x\.com|twitter\.com|linkedin\.com/in/|\.pdf$)", re.I)
PRICING_HINT = re.compile(r"(/(pricing|plans|products?)/?([?#]|$)|gumroad\.com/l/|etsy\.com/listing/|/shop/)", re.I)
PRICING_SLOTS = 2


def gather(run_id: str, queries: list[str]) -> dict[str, Any]:
    c = caps()
    queries = queries[: c["max_queries"]]
    searches, urls = [], []
    for q in queries:
        res = search.search(q, c["results_per_query"])
        searches.append(res)
        decision_log.append(run_id, "market_researcher", "web_search", sources=[r["url"] for r in res["results"]],
                            model=None, query=q, origin=res["origin"], note=res["note"])
        events.emit(run_id, "step", f"search '{q}' -> {len(res['results'])} results ({res['note']})")
    # reserve slots for pricing/product pages: without them the gate never sees a verified price
    lists = [r["results"] for r in searches]
    for r in (r for l in lists for r in l):
        if len(urls) >= PRICING_SLOTS:
            break
        if PRICING_HINT.search(r["url"]) and r["url"] not in urls and not SKIP_HOSTS.search(r["url"]):
            urls.append(r["url"])
    # then round-robin across queries so one query cannot take every slot
    i = 0
    while len(urls) < c["max_pages"] and any(i < len(l) for l in lists):
        for l in lists:
            if i < len(l) and len(urls) < c["max_pages"]:
                u = l[i]["url"]
                if u not in urls and not SKIP_HOSTS.search(u):
                    urls.append(u)
        i += 1
    pages = []
    for u in urls:
        events.check_kill()
        page = reader.fetch(u, c["page_chars"])
        if not page["text"].strip():
            decision_log.append(run_id, "page_reader", "fetch_failed", sources=[u], origin=page["origin"])
            continue
        try:
            extract = reader.read(u, page["text"], run_id=run_id)
        except llm.LLMError as e:
            decision_log.append(run_id, "page_reader", "read_failed", sources=[u], model=e.model, reason=e.detail[:200])
            continue
        last = __import__("app.services.cost", fromlist=["last_call"]).last_call(run_id)
        decision_log.append(run_id, "page_reader", "read_page_isolated", sources=[u], model=llm.model_name("page_reader"),
                            tokens_in=last.get("tokens_in"), tokens_out=last.get("tokens_out"))
        events.emit(run_id, "step", f"read {u} -> {extract.page_kind}" + (f", price {extract.price_text}" if extract.price_text else ""))
        pages.append({**page, "extract": extract.model_dump()})
    return {"searches": searches, "pages": pages}


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

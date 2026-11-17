"""Market Researcher: capped search -> isolated page reader -> claim extraction (atomic, quoted)."""
from __future__ import annotations

import re
from typing import Any

from app import llm
from app.agents import base
from app.config import caps
from app.models import Brief, ClaimList, PageExtract, SearchTerms, now_iso
from app.services import decision_log, events, reader, search
from app.services.search import queries, tavily

COMMUNITY_EXTRACTS = 4
EXTRACTABLE = {"http_403", "http_401", "http_429", "bot_check", "js_required", "too_short", "login_wall", "timeout"}

# reddit.com HTML is never fetched by us (bot checks; a reader once invented quotes from one): Reddit text comes
# only from the official API (app/services/community) or from the page text Tavily's search returned
NO_FETCH = re.compile(r"(^|[/.])(reddit\.com|redd\.it)(/|$)", re.I)
SKIP_HOSTS = re.compile(r"(youtube\.com|facebook\.com|instagram\.com|tiktok\.com|x\.com|twitter\.com|linkedin\.com/in/|\.pdf$)", re.I)


def plan_queries(run_id: str, terms: SearchTerms, idea: str, purposes: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Build queries in code for each purpose ({purpose: competitor name or ''}), lint them, log rejections."""
    c = caps()
    limits = {"demand": c["demand_queries"], "competitors": c["competitor_queries"], "pricing": c["pricing_queries"],
              "pricing_fallback": 1, "alternatives": 1}
    planned = []
    for purpose, competitor in (purposes or {"demand": "", "competitors": ""}).items():
        for q in queries.build(terms, purpose, competitor=competitor, limit=limits[purpose]):
            why = queries.lint(q, idea, purpose=purpose, terms=terms)
            if why:
                decision_log.append(run_id, "market_researcher", "query_rejected", query=q, purpose=purpose, reason=why)
                continue
            planned.append((purpose, q))
    return planned


POOL_SIZE = 12
SNIPPETS_PER_PURPOSE = 3
MIN_SNIPPET = 80


def gather(run_id: str, planned: list[tuple[str, str]], skip: set[str] | None = None,
           max_pages: int | None = None) -> dict[str, Any]:
    """Search each planned query, then per purpose: a pool of up to 12 candidate URLs, fetched until max_pages
    pass the quality check; failures are logged with a reason and replaced by the next candidate. Search
    snippets of failed or empty pages are kept as snippet-only pages (their claims are PARTIAL, never counted)."""
    c = dict(caps())
    if max_pages is not None:  # the research loop's remaining read budget, per purpose
        c["max_pages"] = max(0, min(c["max_pages"], max_pages))
    skip = set(skip or ())
    searches: list[dict[str, Any]] = []
    for purpose, q in planned:
        res = {**search.search(q, c["results_per_query"], purpose, run_id=run_id), "purpose": purpose}
        searches.append(res)
        if "budget" in res.get("note", "") and run_id:
            decision_log.append(run_id, "market_researcher", "tavily_budget_fallback", query=q, purpose=purpose,
                                reason=res["note"])
        decision_log.append(run_id, "market_researcher", "web_search", sources=[r["url"] for r in res["results"]],
                            model=None, query=q, purpose=purpose, origin=res["origin"], note=res["note"],
                            engines=res.get("engines", []), unresponsive=res.get("unresponsive", []))
        events.emit(run_id, "step", f"search '{q}' -> {len(res['results'])} results ({res['note']})")
    pages: list[dict[str, Any]] = []
    # competitor/pricing purposes first: a URL is read once, and only competitor-purpose pages may yield a
    # paying competitor, while demand signals depend on the site and the quote, not on the purpose
    for purpose in sorted(dict.fromkeys(s["purpose"] for s in searches), key=lambda x: x == "demand"):
        lists = [s["results"] for s in searches if s["purpose"] == purpose]
        raw = {r["url"]: r["raw_content"] for l in lists for r in l if r.get("raw_content")} if tavily.enabled() else {}
        via_tavily = {r["url"] for l in lists for r in l if "tavily" in (r.get("engines") or [])}
        pool: list[str] = []
        snippets: dict[str, str] = {}
        for i in range(max((len(l) for l in lists), default=0)):  # round-robin so one query cannot fill the pool
            for l in lists:
                if i < len(l):
                    u = l[i]["url"]
                    snippets.setdefault(u, f'{l[i].get("title", "")}\n{l[i].get("snippet", "")}'.strip())
                    if (len(pool) < POOL_SIZE and u not in pool and u not in skip and not SKIP_HOSTS.search(u)
                            and not (NO_FETCH.search(u) and u not in raw)):
                        pool.append(u)
        events.check_kill()
        # page text that came with the search result is used first (community sites refuse our own fetches)
        pre = [_use_raw(run_id, purpose, {"url": u, "ok": False, "reason": "not_fetched", "structured_prices": [],
                                          "retrieved_at": now_iso()}, raw[u], c) for u in pool if u in raw]
        pre = [p for p in pre if p["ok"]]
        rest = [u for u in pool if u not in {p["url"] for p in pre}]
        no_fetch = [{"url": u, "ok": False, "reason": "no_fetch_reddit", "structured_prices": [], "retrieved_at": now_iso(),
                     "text": "", "origin": "none"} for u in rest if NO_FETCH.search(u)]
        rest = [u for u in rest if not NO_FETCH.search(u)]
        fetched = pre + no_fetch + reader.fetch_many(rest, c["page_chars"], want=max(0, c["max_pages"] - len(pre)))
        fetched = _extract_failed(run_id, purpose, fetched, c, raw)
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
            pages.append({**page, "purpose": purpose, "extract": ex, **({"via": "Tavily"} if u in via_tavily else {})})
        # snippet fallback: the search engine's own text for pages that failed or gave no target fields
        for u in [u for u in fallback if len(snippets.get(u, "")) >= MIN_SNIPPET][:SNIPPETS_PER_PURPOSE]:
            pages.append({**snippet_page(u, snippets[u], purpose), **({"via": "Tavily"} if u in via_tavily else {})})
            decision_log.append(run_id, "market_researcher", "snippet_fallback", sources=[u], purpose=purpose)
    return {"searches": searches, "pages": pages}


def _extract_failed(run_id: str, purpose: str, fetched: list[dict[str, Any]], c: dict[str, Any],
                    raw: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Pages our own fetch could not read (403s, bot walls, JS shells): first the page text Tavily's search
    returned for that URL (origin 'tavily-search-raw'), then one Tavily Extract attempt for the rest, only for as
    many pages as are still missing (+2; community threads for demand always). Either text passes the same
    quality check and goes to the isolated reader. Without a Tavily key nothing changes."""
    if not tavily.enabled():
        return fetched
    fetched = [_use_raw(run_id, purpose, p, raw.get(p["url"], ""), c) if raw and not p["ok"] else p for p in fetched]
    from app.config import gate_definitions
    from app.orchestrator.orchestrator import on_community_site  # lazy: the orchestrator imports this module
    need = c["max_pages"] - sum(p["ok"] for p in fetched)
    failed = [p["url"] for p in fetched if not p["ok"] and p.get("reason") in EXTRACTABLE]
    community = gate_definitions()["desk_gate"]["community_domains"]
    # demand needs first-hand threads, which are exactly the pages that block us: always try those (up to 4)
    picked = [u for u in failed if purpose == "demand" and on_community_site(u, community)][:COMMUNITY_EXTRACTS]
    picked += [u for u in failed if u not in picked][: max(0, need) + 2]
    if not picked:
        return fetched
    failed = picked
    texts = tavily.extract(failed)
    out = []
    for p in fetched:
        text = texts.get(p["url"], "")
        text = clean_markdown(text)
        if not p["ok"] and text and not reader.quality(text):
            decision_log.append(run_id, "page_reader", "tavily_extract", sources=[p["url"]], purpose=purpose,
                                replaced_reason=p["reason"], text_chars=len(text))
            p = {**p, "ok": True, "reason": None, "origin": "tavily-extract", "text": text[: c["page_chars"]]}
        out.append(p)
    return out


def clean_markdown(text: str) -> str:
    """Tavily returns pages as markdown: drop images and link targets so the reading window holds the content."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{3,}", "\n\n", text)).strip()


def _use_raw(run_id: str, purpose: str, page: dict[str, Any], text: str, c: dict[str, Any]) -> dict[str, Any]:
    text = clean_markdown(text)
    if not text or reader.quality(text):
        return page
    decision_log.append(run_id, "page_reader", "tavily_search_raw", sources=[page["url"]], purpose=purpose,
                        replaced_reason=page["reason"], text_chars=len(text))
    return {**page, "ok": True, "reason": None, "origin": "tavily-search-raw", "text": text[: c["page_chars"]]}


FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|my|me|we|we're|our|us)\b", re.I)
SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def first_person_sentence(text: str, terms: list[str]) -> str:
    """The first sentence in first person, preferring one that names a problem word; a substring of `text`."""
    words = {w for t in terms for w in re.findall(r"[a-z]{4,}", t.lower())}
    sents = [m.group(0).strip() for m in SENTENCE.finditer(text) if len(m.group(0).strip()) >= 20]
    fp = [s for s in sents if FIRST_PERSON.search(s)]
    on_topic = [s for s in fp if any(w[:5] in s.lower() for w in words)]
    return (on_topic or fp or sents or [text.strip()])[0][:400]


def community_pages(run_id: str, terms: SearchTerms, skip: set[str] | None = None) -> list[dict[str, Any]]:
    """Community posts from official APIs as pages, WITHOUT an LLM read: the quote and its date come straight
    from the API (the quote is a substring of the post text), so they can always be checked against the source."""
    from app.services import community
    cfg = community.config()
    phrases = [terms.problem] + list(terms.synonyms)
    posts = community.search_community(phrases, terms.audience, cfg.get("max_posts", 10), run_id=run_id,
                                       context=terms.product_type)
    pages = []
    for p in posts:
        if p.url in (skip or set()):
            continue
        text = p.text[: cfg.get("max_text_chars", 3000)]
        quote = first_person_sentence(text, phrases)
        pages.append({"url": p.url, "text": text, "retrieved_at": now_iso(), "origin": f"community-api ({p.source})",
                      "ok": True, "reason": None, "purpose": "demand", "structured_prices": [], "provider": p.source,
                      "thread_title": p.thread_title, "score": p.score, "author_handle_hash": p.author_handle_hash,
                      "extract": {"page_kind": "forum", "product_name": None, "price_text": None, "has_public_price": False,
                                  "features": [], "audience": None,
                                  "problem_statements": [{"quote": quote, "date": p.created_at or None}]}})
        decision_log.append(run_id, "market_researcher", "community_post_added", sources=[p.url], model=None,
                            provider=p.source, created_at=p.created_at, text_chars=len(text))
    events.emit(run_id, "step", f"{len(pages)} community posts from APIs ({', '.join(sorted({p.source for p in posts})) or 'none'})")
    return pages


def snippet_page(url: str, text: str, purpose: str) -> dict[str, Any]:
    """A search-result snippet used as evidence text. No LLM read; claims from it are PARTIAL, 'snippet only'."""
    return {"url": url, "text": text, "retrieved_at": now_iso(), "origin": "search-snippet", "ok": True, "purpose": purpose,
            "snippet_only": True, "structured_prices": [],
            "extract": {"page_kind": "other", "snippet": text, "product_name": None, "price_text": None,
                        "has_public_price": False, "features": [], "problem_statements": [], "audience": None}}


def is_snippet(page: dict[str, Any]) -> bool:
    return bool(page.get("snippet_only"))


EXTRACT_BATCH = 4


def _has_fields(p: dict[str, Any]) -> bool:
    ex = p["extract"]
    return bool(ex.get("problem_statements") or ex.get("price_text") or ex.get("product_name") or ex.get("features")
                or ex.get("snippet"))


def extract_claims(run_id: str, brief: Brief, pages: list[dict[str, Any]]) -> ClaimList:
    """Claims are extracted a few pages at a time: with 20+ pages in one prompt the model returned an empty list.
    Pages with no extracted fields are skipped; an empty answer for a batch with fields is logged."""
    pages = [p for p in pages if _has_fields(p)]
    claims = []
    for i in range(0, len(pages), EXTRACT_BATCH):
        batch = pages[i:i + EXTRACT_BATCH]
        compact = [{"url": p["url"], "retrieved_at": p["retrieved_at"], "fields": p["extract"]} for p in batch]
        out = base.run(run_id, "claim_extractor", "claim_extractor", "extract_atomic_claims", ClaimList,
                       {"idea": brief.idea, "target_market": brief.target_market, "page_extracts": compact},
                       sources=[p["url"] for p in batch],
                       instructions="Write atomic claims (one fact each) ONLY from these page extracts; usually several per "
                                    "page. Types: demand_signal (a person describing this problem in their own words, "
                                    "with date if known), paying_competitor (a product with a visible price), competitor, "
                                    "trend, market_size, compliance, other. source_url must be the URL of the extract the "
                                    "claim comes from; source_quote must be words copied exactly from that extract's fields.")
        if not out.claims and run_id:
            decision_log.append(run_id, "claim_extractor", "claims_empty", sources=[p["url"] for p in batch],
                                reason="model returned no claims for pages with extracted fields")
        claims += out.claims
    return ClaimList(claims=claims)


def normalize(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def quote_in_source(quote: str, text: str) -> bool:
    q = normalize(quote)
    if len(q) < 4:
        return False
    return q in normalize(text)


def page_extract(p: dict[str, Any]) -> PageExtract:
    return PageExtract.model_validate(p["extract"])

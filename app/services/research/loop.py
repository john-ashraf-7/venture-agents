"""Iterative research loop for Phase 1: broad pass -> learn leads -> plan next queries -> search -> read -> repeat.

Code owns the state (queries run, budget, leads, evidence candidates) and every stop rule. The research_planner
role only sees a structured summary (counts vs the locked thresholds, short lead strings, queries already run,
remaining budget); it never sees page text. Every query it proposes is linted in code before it is sent.

Evidence is NOT judged here: pages go back to Phase 1, where quotes are checked against the page text, dates must
come from the source, the demand classifier runs, and the desk gate counts in code. The tallies below are only
candidates ("leads pending verification") used to decide when to stop searching.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.agents import base, market_researcher
from app.config import load_yaml, profile_name
from app.models import Brief, SearchTerms
from app.services import decision_log, events
from app.services.search import queries

Purpose = Literal["demand", "competitors", "pricing", "reviews", "community"]
# planner purposes -> search routes (config/search.yaml) understood by the gatherer
ROUTE = {"demand": "demand", "community": "demand", "competitors": "competitors", "reviews": "competitors",
         "pricing": "pricing"}


class PlannedQuery(BaseModel):
    query: str = Field(description="a short web search query, at most 12 words, no years except the current one")
    purpose: Purpose
    language: str = Field(default="en", description="ISO language code of the query")
    why: str = Field(default="", description="one short reason")


class RoundPlan(BaseModel):
    queries: list[PlannedQuery] = Field(default_factory=list, max_length=4)
    done: bool = Field(default=False, description="true when no further search is likely to add evidence")


def cfg() -> dict[str, Any]:
    return load_yaml("research.yaml")


def budget() -> dict[str, Any]:
    b = cfg()["budget"]
    return dict(b.get(profile_name(), b["default"]))


def _words(q: str) -> set[str]:
    return set(re.findall(r"\w+", q.lower()))


def near_duplicate(q: str, past: list[str], threshold: float) -> bool:
    a = _words(q)
    for p in past:
        b = _words(p)
        if a and b and len(a & b) / len(a | b) >= threshold:
            return True
    return False


def shares_stem(text: str, terms: SearchTerms) -> bool:
    """'invoices' names 'invoice': compare 5-letter stems of content words (the audience's own wording varies)."""
    stems = lambda s: {w[:5] for w in queries.keywords(s) if len(w) >= 4}
    return bool(stems(text) & set().union(*(stems(p) for p in [terms.problem, terms.product_type, *terms.synonyms] if p)))


def lint(q: PlannedQuery, terms: SearchTerms, idea: str, past: list[str], leads: dict[str, list[str]]) -> Optional[str]:
    """Why a planned query is dropped, or None. Reuses the template lint (years, plain 'forum', copied idea)."""
    c = cfg()
    text = re.sub(r"\s+", " ", q.query or "").strip()
    if not text:
        return "empty query"
    if len(text.split()) > int(c.get("max_query_words", 12)):
        return f"more than {c.get('max_query_words', 12)} words"
    for y in re.findall(r"\b(19\d{2}|20\d{2})\b", text):
        if int(y) != datetime.now().year:
            return f"year {y} is not the current year"
    if near_duplicate(text, past, float(c.get("near_duplicate_jaccard", 0.8))):
        return "duplicate or near-duplicate of a query already run"
    anchors = [leads.get("competitors", []), leads.get("communities", [])]
    names_lead = any(n and n.lower() in text.lower() for group in anchors for n in group)
    base_why = queries.lint(text, idea)
    return base_why if base_why and "more than 10 words" not in base_why else None


def _host(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _short(s: str, n: int = 80) -> str:
    return re.sub(r"[^\w\s.&+'-]", " ", s or "").strip()[:n]


def update_leads(leads: dict[str, list[str]], pages: list[dict[str, Any]], rule: dict[str, Any]) -> None:
    """Short strings only: competitor names (sanitised), community hosts, thread titles as audience phrasings."""
    from app.orchestrator.orchestrator import on_community_site  # lazy: the orchestrator imports this module
    cap = int(cfg().get("max_leads", 40))
    for p in pages:
        ex = p.get("extract") or {}
        name = queries.competitor_name(ex.get("product_name") or "")
        if name and ex.get("page_kind") == "product" and name not in leads["competitors"]:
            leads["competitors"].append(name)
        if on_community_site(p["url"], rule.get("community_domains", [])) or p.get("origin", "").startswith("community-api"):
            host = _host(p["url"])
            if host and host not in leads["communities"]:
                leads["communities"].append(host)
        title = _short(p.get("thread_title") or "")
        if title and title not in leads["phrasings"]:
            leads["phrasings"].append(title)
    for k in leads:
        del leads[k][cap:]


def tally(pages: list[dict[str, Any]], rule: dict[str, Any]) -> dict[str, int]:
    """Evidence CANDIDATES for the stop rule (not counted at the gate; Phase 1 verifies them)."""
    from app.orchestrator.orchestrator import COMPETITOR_PURPOSES, on_community_site
    demand = {p["url"] for p in pages
              if (p.get("origin", "").startswith("community-api") or on_community_site(p["url"], rule.get("community_domains", [])))
              and any(ps.get("date") for ps in (p.get("extract") or {}).get("problem_statements", []))}
    priced = {p["url"] for p in pages if p.get("purpose") in COMPETITOR_PURPOSES and not market_researcher.is_snippet(p)
              and ((p.get("extract") or {}).get("price_text") or p.get("structured_prices"))}
    reads = sum(1 for p in pages if not market_researcher.is_snippet(p) and not p.get("origin", "").startswith("community-api"))
    return {"demand_candidates": len(demand), "priced_candidates": len(priced), "page_reads": reads,
            "community_posts": sum(1 for p in pages if p.get("origin", "").startswith("community-api"))}


def summary(terms: SearchTerms, brief: Brief, rule: dict[str, Any], t: dict[str, int], leads: dict[str, list[str]],
            past: list[str], left: dict[str, Any]) -> dict[str, Any]:
    return {"brief_terms": terms.model_dump(), "target_market": brief.target_market,
            "evidence_candidates_vs_locked_thresholds": {
                "demand": f"{t['demand_candidates']} candidates / {rule['demand_signals_min']} needed",
                "priced_competitors": f"{t['priced_candidates']} candidates / {rule['paying_competitors_min']} needed"},
            "leads": leads, "queries_already_run": past, "budget_left": left}


def stop_reason(t: dict[str, int], rule: dict[str, Any], used: dict[str, Any], b: dict[str, Any], stalled: int,
                started: float) -> Optional[str]:
    if t["demand_candidates"] >= int(rule["demand_signals_min"]) and t["priced_candidates"] >= int(rule["paying_competitors_min"]):
        return "locked thresholds reached by candidates (verified in Phase 1)"
    if used["rounds"] >= b["rounds"]:
        return "round budget used"
    if used["searches"] >= b["searches"]:
        return "search budget used"
    if t["page_reads"] >= b["page_reads"]:
        return "page-read budget used"
    if time.time() - started >= b["seconds"]:
        return "time budget used"
    if stalled >= int(cfg().get("stall_rounds", 2)):
        return f"{stalled} rounds in a row without new evidence"
    return None


def run(run_id: str, brief: Brief, terms: SearchTerms, round1: list[tuple[str, str]], rule: dict[str, Any]) -> dict[str, Any]:
    """Returns {"searches", "pages", "rounds", "coverage"}."""
    b, c = budget(), cfg()
    started = time.time()
    research: dict[str, Any] = {"searches": [], "pages": []}
    leads: dict[str, list[str]] = {"phrasings": [], "communities": [], "competitors": []}
    past: list[str] = []
    used = {"rounds": 0, "searches": 0}
    rounds_log: list[dict[str, Any]] = []
    stalled, prev = 0, 0
    why_stop = None
    while True:
        used["rounds"] += 1
        n = used["rounds"]
        if n == 1:
            planned = round1[: b["searches"]]
            per_purpose = int(c.get("round1_pages_per_purpose", 3))
            dropped: list[dict[str, str]] = []
        else:
            t = tally(research["pages"], rule)
            left = {"searches": b["searches"] - used["searches"], "page_reads": b["page_reads"] - t["page_reads"],
                    "rounds": b["rounds"] - n + 1}
            plan = base.run(run_id, "research_planner", "planner", f"plan_research_round_{n}", RoundPlan,
                            {"research_state": summary(terms, brief, rule, t, leads, past, left)},
                            instructions=f"Propose up to {c.get('queries_per_round', 3)} new web search queries that fill "
                                         "the biggest gap. Use the audience's own words and the target market's language. "
                                         "Use competitor names for 'alternatives to', complaints and reviews; use community "
                                         "names to search inside them. Never repeat a query. Set done=true if more search "
                                         "is unlikely to help.")
            planned, dropped = [], []
            for q in plan.queries[: int(c.get("queries_per_round", 3))]:
                why = lint(q, terms, brief.idea, past + [x for _, x in planned], leads)
                if why:
                    dropped.append({"query": q.query, "purpose": q.purpose, "reason": why})
                else:
                    planned.append((ROUTE[q.purpose], q.query.strip()))
            if n == 2 and leads["competitors"]:  # competitors are a way in: price the first one found, built in code
                top = leads["competitors"][0]
                pq = queries.build(terms, "pricing", competitor=top, limit=1)
                if pq and not near_duplicate(pq[0], past, float(c.get("near_duplicate_jaccard", 0.8))):
                    planned.insert(0, ("pricing", pq[0]))
            planned = planned[: max(0, b["searches"] - used["searches"])]
            per_purpose = max(0, min(3, b["page_reads"] - t["page_reads"]))
            if plan.done and not planned:
                why_stop = "planner: further search unlikely to help"
        events.emit(run_id, "step", f"Research round {n}: " + (", ".join(q for _, q in planned) or "no new queries"))
        if planned:
            got = market_researcher.gather(run_id, planned, skip={p["url"] for p in research["pages"]}, max_pages=per_purpose)
            research["searches"] += got["searches"]
            research["pages"] += got["pages"]
            used["searches"] += len(planned)
            past += [q for _, q in planned]
            demand_terms = [q for p, q in planned if p == "demand"]
            if n == 1:  # community APIs (HN, Stack Exchange, Reddit with keys) with the brief's own keywords
                research["pages"] += market_researcher.community_pages(run_id, terms, skip={p["url"] for p in research["pages"]})
            elif demand_terms:
                extra = SearchTerms(problem=terms.problem, audience=terms.audience, product_type=terms.product_type,
                                    synonyms=[queries.competitor_name(q) or q[:40] for q in demand_terms][:3])
                research["pages"] += market_researcher.community_pages(run_id, extra, skip={p["url"] for p in research["pages"]})
        update_leads(leads, research["pages"], rule)
        t = tally(research["pages"], rule)
        new = t["demand_candidates"] + t["priced_candidates"]
        stalled = stalled + 1 if new <= prev else 0
        prev = new
        rec = {"round": n, "queries": [q for _, q in planned], "dropped": dropped, **t,
               "seconds": round(time.time() - started, 1)}
        rounds_log.append(rec)
        decision_log.append(run_id, "research_loop", "research_round", sources=[], model=None, **rec,
                            leads={k: len(v) for k, v in leads.items()})
        why_stop = why_stop or stop_reason(t, rule, used, b, stalled, started)
        if why_stop or not planned and n > 1:
            why_stop = why_stop or "no valid queries this round"
            break
    coverage = {"rounds": used["rounds"], "searches": used["searches"], "page_reads": t["page_reads"],
                "community_posts": t["community_posts"], "verifiable_sources": t["demand_candidates"] + t["priced_candidates"],
                "language": "en", "stop_reason": why_stop, "seconds": round(time.time() - started, 1)}
    decision_log.append(run_id, "research_loop", "research_stopped", sources=[], model=None, **coverage)
    events.emit(run_id, "step", f"Research stopped after {used['rounds']} round(s): {why_stop}")
    return {**research, "rounds": rounds_log, "coverage": coverage, "leads": leads}

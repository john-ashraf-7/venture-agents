"""Research loop: query lint, stop rules, and low coverage -> PARK (never STOP)."""
import time

from app import gates
from app.models import SearchTerms
from app.services.research import loop

TERMS = SearchTerms(problem="late invoice payments", audience="freelance designers", product_type="invoice templates")
RULE = {"demand_signals_min": 3, "paying_competitors_min": 1}


def q(text, purpose="demand"):
    return loop.PlannedQuery(query=text, purpose=purpose)


def test_lint_drops_long_stale_duplicate_and_off_topic_queries():
    leads = {"competitors": ["FreshBooks"], "communities": [], "phrasings": []}
    past = ["late invoice payments reminder"]
    assert loop.lint(q("one two three four five six seven eight nine ten eleven twelve thirteen"), TERMS, "", past, leads)
    assert loop.lint(q("late invoice payments 2019"), TERMS, "", past, leads)
    assert loop.lint(q("reminder late invoice payments"), TERMS, "", past, leads)  # near-duplicate
    assert loop.lint(q("best laptop deals"), TERMS, "", past, leads)  # no brief term, competitor or community
    assert loop.lint(q("alternatives to FreshBooks", "competitors"), TERMS, "", past, leads) is None
    assert loop.lint(q("clients never pay invoices on time", "demand"), TERMS, "", past, leads) is None


def test_stop_rules():
    b = {"rounds": 4, "searches": 12, "page_reads": 15, "seconds": 90}
    t = {"demand_candidates": 0, "priced_candidates": 0, "page_reads": 3, "community_posts": 0}
    now = time.time()
    assert loop.stop_reason(t, RULE, {"rounds": 1, "searches": 4}, b, 0, now) is None
    assert "round" in loop.stop_reason(t, RULE, {"rounds": 4, "searches": 4}, b, 0, now)
    assert "search" in loop.stop_reason(t, RULE, {"rounds": 2, "searches": 12}, b, 0, now)
    assert "without new evidence" in loop.stop_reason(t, RULE, {"rounds": 2, "searches": 4}, b, 2, now)
    assert "time" in loop.stop_reason(t, RULE, {"rounds": 2, "searches": 4}, b, 0, now - 100)
    met = {**t, "demand_candidates": 3, "priced_candidates": 1}
    assert "thresholds" in loop.stop_reason(met, RULE, {"rounds": 1, "searches": 4}, b, 0, now)


def _ev(demand, pages, sources):
    return gates.DeskEvidence(demand_signals=demand, paying_competitors=0, direct_competitors=0, blocking_flags=0,
                              cost_high_usd=10, budget_usd=100, hours_high=1, hours_available=10,
                              coverage_pages=pages, coverage_sources=sources)


def test_low_coverage_parks_instead_of_stopping():
    rule = {"demand_signals_min": 3, "paying_competitors_min": 1, "direct_competitors_max": 4,
            "blocking_compliance_flags_max": 0, "coverage_min": {"pages_read": 5, "verifiable_sources": 1}}
    low = gates.desk_gate(rule, _ev(0, 2, 0))
    assert low.verdict.value == "PARK" and "Not enough searchable evidence" in low.reasons[0]
    searched = gates.desk_gate(rule, _ev(0, 20, 4))
    assert searched.verdict.value == "STOP"
    flagged = gates.DeskEvidence(**{**_ev(0, 2, 0).__dict__, "blocking_flags": 1})
    assert gates.desk_gate(rule, flagged).verdict.value == "STOP"  # a compliance block is never softened

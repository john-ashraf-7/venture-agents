"""Planner: estimates effort/cost as ASSUMPTION ranges and writes the search queries.

Runs BEFORE any web content is read (plan-then-execute): retrieved text can never add steps.
"""
from __future__ import annotations

from app.agents import base
from app.models import PRD, Brief, IdeaMatrix, LeanCanvas, PlanEstimate
from app.services import decision_log, keywords


def estimate(run_id: str, brief: Brief, lessons: list[str]) -> PlanEstimate:
    """Keywords are code-checked against the brief: one corrective retry, then brief noun phrases."""
    plan = base.run(run_id, "planner", "planner", "estimate_plan_and_queries", PlanEstimate,
                    {"brief": brief, "lessons_from_earlier_runs": lessons},
                    instructions="Estimate hours and cost to reach a first sellable version as low-high ranges "
                                 "(these are ASSUMPTIONS). Fill search_terms with short keywords only (no years, no "
                                 "full sentences, do not copy the idea text): the buyer's problem as they would say it, "
                                 "the buyer, the product type, and up to 3 synonyms. Use words from the brief. "
                                 "Code builds the search queries.",
                    check=keywords.check_message(brief))
    if keywords.off_brief_terms(plan.search_terms, brief):
        plan.search_terms, replaced = keywords.fallback(plan.search_terms, brief)
        if run_id:
            decision_log.append(run_id, "planner", "keywords_fallback_to_brief", model=None, replaced=replaced,
                                search_terms=plan.search_terms.model_dump())
    return plan


def prd(run_id: str, brief: Brief, ideas: IdeaMatrix, canvas: LeanCanvas | None) -> PRD:
    return base.run(run_id, "planner", "planner", "write_prd", PRD,
                    {"brief": brief, "theory_of_value": ideas.theory_of_value, "lean_canvas": canvas},
                    instructions="Write a PRD for ONE digital guide/template pack (static HTML + Markdown). "
                                 "List 3-8 required section headings.")

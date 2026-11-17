"""Planner: estimates effort/cost as ASSUMPTION ranges and writes the search queries.

Runs BEFORE any web content is read (plan-then-execute): retrieved text can never add steps.
"""
from __future__ import annotations

from app.agents import base
from app.models import PRD, Brief, IdeaMatrix, LeanCanvas, PlanEstimate


def estimate(run_id: str, brief: Brief, lessons: list[str]) -> PlanEstimate:
    return base.run(run_id, "planner", "planner", "estimate_plan_and_queries", PlanEstimate,
                    {"brief": brief, "lessons_from_earlier_runs": lessons},
                    instructions="Estimate hours and cost to reach a first sellable version as low-high ranges "
                                 "(these are ASSUMPTIONS). Write 3-6 specific web search queries that would find: people "
                                 "describing this problem in forums, existing paid products with pricing pages, and trends.")


def prd(run_id: str, brief: Brief, ideas: IdeaMatrix, canvas: LeanCanvas | None) -> PRD:
    return base.run(run_id, "planner", "planner", "write_prd", PRD,
                    {"brief": brief, "theory_of_value": ideas.theory_of_value, "lean_canvas": canvas},
                    instructions="Write a PRD for ONE digital guide/template pack (static HTML + Markdown). "
                                 "List 3-8 required section headings.")

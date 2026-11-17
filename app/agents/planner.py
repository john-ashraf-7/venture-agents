"""Planner: estimates effort/cost as ASSUMPTION ranges and writes the search queries.

Runs BEFORE any web content is read (plan-then-execute): retrieved text can never add steps.
"""
from __future__ import annotations

from typing import Any

from app.agents import base
from app.config import load_yaml
from app.models import PRD, Brief, IdeaMatrix, LeanCanvas, PlanEstimate
from app.services import decision_log, keywords

MAX_ADJUST = 0.5  # the model may move a baseline range by at most +-50%, and only with a stated reason


def baseline_for(product_type: str) -> tuple[str, dict[str, Any]]:
    """Map the brief's product type to a baseline (config/product_type_baselines.yaml) by keyword; else `default`."""
    table = load_yaml("product_type_baselines.yaml")["baselines"]
    text = (product_type or "").lower()
    for key, b in table.items():
        if key != "default" and any(k in text for k in b.get("keywords", [])):
            return key, b
    return "default", table["default"]


def clamp(plan: PlanEstimate, key: str, b: dict[str, Any]) -> PlanEstimate:
    """Clamp to [0.5 x baseline low, 1.5 x baseline high] when the model gave a reason, else to [low, high]."""
    (h_lo, h_hi), (c_lo, c_hi) = b["hours"], b["cost_usd"]
    reason = (plan.adjustment_reason or "").strip()
    f_lo, f_hi = (1 - MAX_ADJUST, 1 + MAX_ADJUST) if reason else (1.0, 1.0)
    raw = {"hours_low": plan.hours_low, "hours_high": plan.hours_high,
           "cost_low_usd": plan.cost_low_usd, "cost_high_usd": plan.cost_high_usd}

    def fit(v: float, lo: float, hi: float) -> float:
        return float(min(max(v, lo), hi))

    plan.hours_low = fit(plan.hours_low, h_lo * f_lo, h_hi * f_hi)
    plan.hours_high = fit(max(plan.hours_high, plan.hours_low), h_lo * f_lo, h_hi * f_hi)
    plan.cost_low_usd = fit(plan.cost_low_usd, c_lo * f_lo, c_hi * f_hi)
    plan.cost_high_usd = fit(max(plan.cost_high_usd, plan.cost_low_usd), c_lo * f_lo, c_hi * f_hi)
    plan.adjustment_reason = reason or None
    plan.baseline_key = key
    plan.baseline = {"label": b.get("label", key), "hours": list(b["hours"]), "cost_usd": list(b["cost_usd"]),
                     "allowed_hours": [h_lo * f_lo, h_hi * f_hi], "allowed_cost_usd": [c_lo * f_lo, c_hi * f_hi]}
    plan.model_estimate = raw
    plan.clamped = any(raw[k] != getattr(plan, k) for k in raw)
    return plan


def estimate(run_id: str, brief: Brief, lessons: list[str]) -> PlanEstimate:
    """Keywords are code-checked against the brief: one corrective retry, then brief noun phrases.
    Hours/cost start from a product-type baseline (ASSUMPTION) and are clamped in code."""
    key, b = baseline_for(brief.product_type)
    baseline = {"product_type": b.get("label", key), "hours": b["hours"], "cash_cost_usd": b["cost_usd"],
                "note": "ASSUMPTION baseline for a first sellable version; cash cost = tools and assets only"}
    plan = base.run(run_id, "planner", "planner", "estimate_plan_and_queries", PlanEstimate,
                    {"brief": brief, "baseline_estimate": baseline, "lessons_from_earlier_runs": lessons},
                    instructions="Estimate hours and cash cost to reach a first sellable version as low-high ranges "
                                 "(these are ASSUMPTIONS). Start from baseline_estimate. You may move a range by at "
                                 "most 50% and only if something in the brief justifies it; then say why in "
                                 "adjustment_reason (otherwise leave it null and keep the baseline). Fill search_terms with short keywords only (no years, no "
                                 "full sentences, do not copy the idea text): the buyer's problem as they would say it, "
                                 "the buyer, the product type, and up to 3 synonyms. Use words from the brief. "
                                 "Code builds the search queries.",
                    check=keywords.check_message(brief))
    plan = clamp(plan, key, b)
    if run_id:
        decision_log.append(run_id, "planner", "clamp_estimate_to_baseline", model=None, baseline_key=key,
                            model_estimate=plan.model_estimate, clamped=plan.clamped,
                            adjustment_reason=plan.adjustment_reason,
                            estimate={"hours": [plan.hours_low, plan.hours_high],
                                      "cost_usd": [plan.cost_low_usd, plan.cost_high_usd]})
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

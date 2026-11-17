"""Experiment Designer: proposes a demand test for the riskiest assumption, with a threshold from a
sourced benchmark or a labeled ASSUMPTION, min_visitors and a window. The founder approves; then it locks."""
from __future__ import annotations

from typing import Any

from app.agents import base
from app.config import gate_definitions
from app.models import Brief, Claim, ExperimentPlan, Label


def run(run_id: str, brief: Brief, riskiest: list[dict[str, Any]], claims: list[Claim]) -> ExperimentPlan:
    d = gate_definitions()["experiment_gate"]
    benchmarks = [{"id": c.id, "text": c.text} for c in claims if c.label == Label.SUPPORTED and c.type in ("trend", "market_size", "other")]
    plan = base.run(run_id, "experiment_designer", "analyst", "design_experiment", ExperimentPlan,
                    {"brief": brief, "riskiest_assumption_first": riskiest[:3], "sourced_benchmarks": benchmarks,
                     "defaults": d},
                    instructions="Design a landing-page waitlist test of the TOP riskiest assumption. Use a sourced "
                                 "benchmark (benchmark_claim_id) for the threshold if one fits, else threshold_source="
                                 "'ASSUMPTION'. State what result would change our mind.")
    if plan.threshold_source == "benchmark" and plan.benchmark_claim_id not in {b["id"] for b in benchmarks}:
        plan.threshold_source, plan.benchmark_claim_id = "ASSUMPTION", None
    if riskiest:
        plan.assumption_tested = riskiest[0]["text"]
    return plan

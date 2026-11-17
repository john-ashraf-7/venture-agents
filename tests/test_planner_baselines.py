"""Planner estimates start from a product-type baseline (ASSUMPTION) and are clamped in code."""
import json

from app.agents import planner
from app.models import Brief, PlanEstimate, SearchTerms
from tests.conftest import stub_backend

TERMS = SearchTerms(problem="late invoice payments", audience="freelancers", product_type="invoice templates",
                    synonyms=["clients paying late"])


def _plan(**kw):
    base = dict(hours_low=20, hours_high=40, cost_low_usd=50, cost_high_usd=200, required_skills=[], search_terms=TERMS)
    return PlanEstimate(**{**base, **kw})


def test_product_type_maps_to_baseline():
    assert planner.baseline_for("guide/template pack")[0] == "template_pack"
    assert planner.baseline_for("Invoicing checklist")[0] == "template_pack"
    assert planner.baseline_for("small static web tool (calculator)")[0] == "static_web_tool"
    assert planner.baseline_for("audio course")[0] == "default"


def test_clamp_without_reason_keeps_baseline_range():
    key, b = planner.baseline_for("template pack")  # hours 10-40, $0-150
    p = planner.clamp(_plan(hours_low=20, hours_high=60, cost_low_usd=100, cost_high_usd=600), key, b)
    assert (p.hours_low, p.hours_high, p.cost_low_usd, p.cost_high_usd) == (20, 40, 100, 150)
    assert p.clamped and p.model_estimate["cost_high_usd"] == 600


def test_clamp_with_reason_allows_at_most_50_percent():
    key, b = planner.baseline_for("template pack")
    p = planner.clamp(_plan(hours_low=1, hours_high=200, cost_low_usd=0, cost_high_usd=600,
                            adjustment_reason="Brief asks for 40 templates in two languages"), key, b)
    assert (p.hours_low, p.hours_high, p.cost_high_usd) == (5, 60, 225)
    assert p.clamped


def test_estimate_inside_bounds_is_not_clamped():
    key, b = planner.baseline_for("template pack")
    p = planner.clamp(_plan(hours_low=15, hours_high=35, cost_low_usd=0, cost_high_usd=100), key, b)
    assert not p.clamped and p.hours_high == 35


def test_stubbed_planner_output_is_clamped():
    """The STUBBED planner replies $50-$200; the template-pack baseline caps cash cost at $150."""
    assert json.loads(stub_backend(None, [{"role": "user", "content": ""}], {"title": "PlanEstimate"}, 0)[0])["cost_high_usd"] == 200
    brief = Brief(idea="Invoice reminder templates for freelancers", product_type="guide/template pack", budget_usd=300)
    p = planner.estimate("", brief, [])
    assert p.baseline_key == "template_pack" and p.clamped
    assert p.cost_high_usd == 150 and p.hours_high == 40

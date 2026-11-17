"""Lean Canvas: every box item is ASSUMPTION unless it cites a SUPPORTED ledger claim (checked in code).
Also ranks open assumptions by impact x uncertainty (riskiest-assumption-first)."""
from __future__ import annotations

from typing import Any

from app.agents import base
from app.models import Brief, Claim, IdeaMatrix, Label, LeanCanvas

BOXES = ["problem", "customer_segments", "unique_value_proposition", "solution", "channels", "revenue_streams",
         "cost_structure", "key_metrics", "unfair_advantage"]


def run(run_id: str, brief: Brief, ideas: IdeaMatrix, claims: list[Claim]) -> LeanCanvas:
    supported = [{"id": c.id, "text": c.text} for c in claims if c.label == Label.SUPPORTED]
    canvas = base.run(run_id, "lean_canvas", "analyst", "write_lean_canvas", LeanCanvas,
                      {"brief": brief, "theory_of_value": ideas.theory_of_value, "supported_claims": supported},
                      instructions="Fill every Lean Canvas box (1-3 items each). Set claim_id only when one of the "
                                   "supported_claims directly backs the item; otherwise null (it becomes an ASSUMPTION). "
                                   "List at least 3 open assumptions with impact and uncertainty 1-5.")
    valid = {c["id"] for c in supported}
    for box in BOXES:
        for item in getattr(canvas, box):
            if item.claim_id and item.claim_id not in valid:
                item.claim_id = None
    return canvas


def labeled(canvas: LeanCanvas) -> dict[str, list[dict[str, Any]]]:
    return {box: [{"text": i.text, "label": "SUPPORTED" if i.claim_id else "ASSUMPTION", "claim_id": i.claim_id}
                  for i in getattr(canvas, box)] for box in BOXES}


def riskiest(canvas: LeanCanvas) -> list[dict[str, Any]]:
    ranked = sorted(canvas.assumptions, key=lambda a: a.impact * a.uncertainty, reverse=True)
    return [{"rank": i + 1, "text": a.text, "impact": a.impact, "uncertainty": a.uncertainty, "risk": a.impact * a.uncertainty}
            for i, a in enumerate(ranked)]

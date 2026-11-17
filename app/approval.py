"""Founder approval. The founder makes every final call; the code enforces how.

- Overriding a STOP (or any recommendation) requires a typed reason.
- "Are you sure?" without new evidence never changes the recommendation.
- The STOP memo is still written, with the override and reason next to it.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.models import Verdict, now_iso
from app.services import decision_log

SYCOPHANCY_PATTERNS = re.compile(
    r"(are you sure|really\??$|i'?m (sure|certain|confident)|trust me|this will work|i know it will|"
    r"just say go|please reconsider|i believe in (it|this)|everyone (loves|wants) it)", re.I)


class ApprovalError(ValueError):
    pass


def decide(run_id: str, gate: str, recommendation: Verdict, choice: str, reason: str = "",
           options: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    choice_v = Verdict(choice)
    override = choice_v != recommendation
    if override and len(reason.strip()) < 10:
        raise ApprovalError("Overriding the recommendation requires a typed reason (at least 10 characters).")
    entry = decision_log.append(
        run_id, "founder", f"gate_decision_{gate}", approved_by="founder",
        options_considered=[o["choice"] for o in (options or [])], initiated_by="agent", chosen_by="founder",
        recommendation=recommendation.value, outcome=choice_v.value.lower(), override=override,
        override_reason=reason.strip() or None)
    return {"gate": gate, "recommendation": recommendation.value, "choice": choice_v.value, "override": override,
            "reason": reason.strip() or None, "decided_at": now_iso(), "log": entry}


def reconsider(recommendation: Verdict, founder_message: str, new_evidence_claim_ids: Optional[list[str]] = None) -> dict[str, Any]:
    """Pressure without new evidence does not move the recommendation."""
    if new_evidence_claim_ids:
        return {"recommendation": recommendation.value, "changed": False,
                "message": "New evidence was attached; the gate will be recomputed from the ledger by code."}
    return {"recommendation": recommendation.value, "changed": False,
            "message": f"Still {recommendation.value}. Confidence or pressure is not evidence; the verdict only changes "
                       "if the ledger changes (new SUPPORTED claims) against the locked rule."}

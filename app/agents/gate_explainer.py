"""Gate Explainer: explains a code-computed verdict. It sees only the locked rule and the numbers,
never the founder's hopes or raw text. First sentence = the recommendation (enforced in code)."""
from __future__ import annotations

from typing import Any

from app import gates
from app.agents import base
from app.models import DevilsAdvocate, GateExplanation


def explain(run_id: str, result: gates.GateResult, locked_rule: dict[str, Any]) -> str:
    facts = {"gate": result.gate, "verdict_computed_by_code": result.verdict.value, "state": result.state,
             "checks": [c.__dict__ for c in result.checks], "reasons": result.reasons, "locked_rule": locked_rule}
    try:
        out = base.run(run_id, "gate_explainer", "gate_explainer", f"explain_{result.gate}_gate", GateExplanation,
                       {"gate_facts": facts},
                       instructions=f"Explain this verdict in 3-5 sentences. Your first sentence must be exactly "
                                    f"'{gates.recommendation_sentence(result.verdict)}' Do not change or soften the verdict.")
        text = out.text
    except Exception as e:  # the verdict stands even if the explainer fails
        text = "Explanation unavailable (" + type(e).__name__ + "). " + " ".join(result.reasons)
    return gates.enforce_first_sentence(text, result.verdict)


def devils_advocate(run_id: str, result: gates.GateResult) -> DevilsAdvocate:
    facts = {"verdict": result.verdict.value, "checks": [c.__dict__ for c in result.checks], "reasons": result.reasons}
    try:
        return base.run(run_id, "devils_advocate", "devils_advocate", f"bull_bear_{result.gate}", DevilsAdvocate,
                        {"gate_facts": facts},
                        instructions="Give the strongest bull case and bear case in 2 sentences each, using only these facts.")
    except Exception as e:
        return DevilsAdvocate(bull_case="unavailable", bear_case=f"unavailable ({type(e).__name__})")

"""Gate Explainer: explains a code-computed verdict. It sees only the locked rule and the numbers,
never the founder's hopes or raw text. First sentence = the recommendation (enforced in code)."""
from __future__ import annotations

import re
from typing import Any

from app import gates
from app.agents import base
from app.models import DevilsAdvocate, GateExplanation

OBSERVER = None  # evals: called with the model's first reply text (verdict-first rate)


def explain(run_id: str, result: gates.GateResult, locked_rule: dict[str, Any]) -> str:
    facts = {"gate": result.gate, "verdict_computed_by_code": result.verdict.value, "state": result.state,
             "checks": [c.__dict__ for c in result.checks], "reasons": result.reasons, "locked_rule": locked_rule}
    replies: list[str] = []

    def verdict_first(out: GateExplanation) -> str | None:
        replies.append(out.text)
        if OBSERVER and len(replies) == 1:
            OBSERVER(out.text)
        if verdict_first_ok(out.text, result.verdict):
            return None
        return (f"Your first sentence must start with the verdict word {result.verdict.value} and name no other "
                f"verdict. Start with exactly '{gates.recommendation_sentence(result.verdict)}'")
    try:
        out = base.run(run_id, "gate_explainer", "gate_explainer", f"explain_{result.gate}_gate", GateExplanation,
                       {"gate_facts": facts},
                       instructions=f"Explain this verdict in 3-5 sentences. Your first sentence must be exactly "
                                    f"'{gates.recommendation_sentence(result.verdict)}' Do not change or soften the verdict.",
                       check=verdict_first, check_retries=2)
        text = out.text
    except Exception as e:  # the verdict stands even if the explainer fails
        text = "Explanation unavailable (" + type(e).__name__ + "). " + " ".join(result.reasons)
    if not verdict_first_ok(text, result.verdict):  # after 2 retries: code states the verdict
        text = gates.recommendation_sentence(result.verdict) + " " + text
    return gates.enforce_first_sentence(text, result.verdict)


def verdict_first_ok(text: str, verdict: gates.Verdict) -> bool:
    """First sentence starts with the code-computed verdict word (after an optional 'Recommendation:')
    and names no other verdict."""
    first = gates.first_sentence(text)
    head = re.sub(r"^\W*(recommendation\s*:\s*)?", "", first, flags=re.I).upper().replace("PIVOT BACK", "PIVOT_BACK").replace("PIVOT-BACK", "PIVOT_BACK")
    return bool(re.match(rf"{verdict.value}(?![A-Z0-9_])", head)) and gates.verdicts_in(first) == {verdict}


def devils_advocate(run_id: str, result: gates.GateResult) -> DevilsAdvocate:
    facts = {"verdict": result.verdict.value, "checks": [c.__dict__ for c in result.checks], "reasons": result.reasons}
    try:
        return base.run(run_id, "devils_advocate", "devils_advocate", f"bull_bear_{result.gate}", DevilsAdvocate,
                        {"gate_facts": facts},
                        instructions="Give the strongest bull case and bear case in 2 sentences each, using only these facts. "
                                     "Quote every number exactly as given (e.g. 1 direct competitor is not 'no direct "
                                     "competitors') and never contradict a check's value.")
    except Exception as e:
        return DevilsAdvocate(bull_case="unavailable", bear_case=f"unavailable ({type(e).__name__})")

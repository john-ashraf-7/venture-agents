"""Claim Checker: factored verification.

Each claim is checked in a FRESH prompt against the fetched source text only (never the draft),
by a different model family from the writer.
"""
from __future__ import annotations

from typing import Optional

from app import llm
from app.config import prompt
from app.models import CheckResult, Claim, Label
from app.services import cost, decision_log, ledger, reader


def excerpt(text: str, quote: str, width: int = 1500) -> str:
    from app.agents.market_researcher import normalize
    low = text.lower()
    i = low.find((quote or "")[:40].lower())
    if i < 0:
        i = 0
    return text[max(0, i - width // 2): i + width]


def check(run_id: str, claim: Claim, source_text: str) -> Claim:
    if not claim.source_url or not source_text:
        return ledger.rewrite_unsupported(claim)
    res = llm.call("claim_checker", [
        {"role": "system", "content": prompt("claim_checker")},
        {"role": "user", "content": f"CLAIM: {claim.text}\nSOURCE URL: {claim.source_url}\n" + reader.wrap(excerpt(source_text, claim.source_quote or ""))},
    ], CheckResult, run_id=run_id)
    spec = llm.resolve("claim_checker")
    claim.checked_by_model = spec.model.name
    claim.checked_by_family = spec.model.family
    claim.label = Label(res.label)
    claim.note = res.reason[:300]
    last = cost.last_call(run_id)
    decision_log.append(run_id, "claim_checker", "verify_claim", sources=[claim.source_url], model=spec.model.name,
                        claim_id=claim.id, label=claim.label.value, tokens_in=last.get("tokens_in"), tokens_out=last.get("tokens_out"))
    if claim.label == Label.UNSUPPORTED:
        return ledger.rewrite_unsupported(claim)
    ledger.update(claim)
    return claim


def check_against_ledger(run_id: str, statement: str, supporting_claim: Optional[Claim], source_text: str) -> str:
    """For public-facing copy: verify one statement against the source of the ledger claim it cites."""
    if not supporting_claim or not supporting_claim.source_url:
        return "ASSUMPTION"
    res = llm.call("claim_checker", [
        {"role": "system", "content": prompt("claim_checker")},
        {"role": "user", "content": f"CLAIM: {statement}\nSOURCE URL: {supporting_claim.source_url}\n"
                                    + reader.wrap(excerpt(source_text, supporting_claim.source_quote or ""))},
    ], CheckResult, run_id=run_id)
    return res.label

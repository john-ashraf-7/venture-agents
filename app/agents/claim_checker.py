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


def label_claim(claim_text: str, source_url: str, source_text: str, quote: str = "", *,
                run_id: Optional[str] = None, use_cache: bool = True) -> CheckResult:
    """One claim against its source, by whichever model the claim_checker role names.
    local_transformers (MiniCheck): best 3 chunks of the full source, max support probability per
    sentence of the claim, mapped to labels by the role's t_high / t_low bands. Otherwise: an LLM prompt."""
    spec = llm.resolve("claim_checker")
    if spec.model.provider_kind == "local_transformers":
        return minicheck_label(spec, claim_text, source_text)
    return llm.call("claim_checker", [
        {"role": "system", "content": prompt("claim_checker")},
        {"role": "user", "content": f"CLAIM: {claim_text}\nSOURCE URL: {source_url}\n" + reader.wrap(excerpt(source_text, quote))},
    ], CheckResult, run_id=run_id, use_cache=use_cache)


def band(p: float, t_high: float, t_low: float) -> str:
    return "SUPPORTED" if p >= t_high else ("PARTIAL" if p >= t_low else "UNSUPPORTED")


def combine(labels: list[str]) -> str:
    """SUPPORTED only if every sentence is; UNSUPPORTED only if none is supported at all; else PARTIAL."""
    if all(x == "SUPPORTED" for x in labels):
        return "SUPPORTED"
    if all(x == "UNSUPPORTED" for x in labels):
        return "UNSUPPORTED"
    return "PARTIAL"


def minicheck_scores(spec: llm.RoleSpec, claim_text: str, source_text: str) -> list[float]:
    """Max support probability over the top-k source chunks, for each sentence of the claim."""
    from app.llm import local_transformers as lt
    k = int(spec.extra.get("top_chunks", 3))
    parts = lt.split_sentences(claim_text)
    pairs, owners = [], []
    for i, part in enumerate(parts):
        for ch in lt.best_chunks(source_text, part, k=k, words=int(spec.extra.get("chunk_words", 300))) or [""]:
            pairs.append((ch, part))
            owners.append(i)
    probs = lt.minicheck_scores(spec.model, pairs)
    best = [0.0] * len(parts)
    for i, p in zip(owners, probs):
        best[i] = max(best[i], p)
    return best


def minicheck_label(spec: llm.RoleSpec, claim_text: str, source_text: str) -> CheckResult:
    t_high, t_low = float(spec.extra.get("t_high", 0.9)), float(spec.extra.get("t_low", 0.5))
    best = minicheck_scores(spec, claim_text, source_text)
    label = combine([band(p, t_high, t_low) for p in best])
    return CheckResult(label=label, reason=f"MiniCheck support probability per sentence: {[round(p, 3) for p in best]} "
                                           f"(SUPPORTED >= {t_high}, PARTIAL >= {t_low})")


def check(run_id: str, claim: Claim, source_text: str) -> Claim:
    if not claim.source_url or not source_text:
        return ledger.rewrite_unsupported(claim)
    res = label_claim(claim.text, claim.source_url, source_text, claim.source_quote or "", run_id=run_id)
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
    return label_claim(statement, supporting_claim.source_url, source_text, supporting_claim.source_quote or "",
                       run_id=run_id).label

"""Per-artifact quality score, cross-phase consistency check, and public-copy verification."""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel

from app.models import Claim, Label
from app.services import ledger


def completeness(obj: BaseModel) -> float:
    data = obj.model_dump()
    fields = list(data.values())
    filled = sum(1 for v in fields if v not in (None, "", [], {}))
    return filled / (len(fields) or 1)


def score(obj: BaseModel, claims: list[Claim]) -> dict[str, Any]:
    m = ledger.metrics(claims)
    cov = m["citation_coverage"] if m["citation_coverage"] is not None else 0.0
    prec = m["citation_precision"] if m["citation_precision"] is not None else 0.0
    comp = completeness(obj)
    total = round((cov + prec + comp) / 3, 3)
    return {"citation_coverage": cov, "citation_precision": prec, "completeness": round(comp, 3), "score": total}


FACTUAL = re.compile(r"(\d|%|percent|million|billion|most |majority|studies|research shows|survey|according to|"
                     r"growing|trend|fastest|leading|#1|number one|best[- ]selling)", re.I)


def factual_sentences(text: str) -> list[str]:
    sents = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip() for s in sents if s.strip() and FACTUAL.search(s) and not re.search(r"\$\s?\d", s)]


def best_claim(sentence: str, claims: list[Claim]) -> Optional[Claim]:
    words = set(re.findall(r"\w{4,}", sentence.lower()))
    best, best_s = None, 0.0
    for c in claims:
        if c.label != Label.SUPPORTED:
            continue
        cw = set(re.findall(r"\w{4,}", c.text.lower()))
        s = len(words & cw) / (len(words | cw) or 1)
        if s > best_s:
            best, best_s = c, s
    return best if best_s >= 0.15 else None


def consistency(canvas: Any, pricing: Any, store_page: Any = None, prd: Any = None) -> list[str]:
    """Later artifacts vs the Lean Canvas and locked assumptions. Returns human-readable mismatches."""
    issues: list[str] = []
    if pricing is not None and canvas is not None:
        rev = " ".join(i.text.lower() for i in canvas.revenue_streams)
        if any(w in rev for w in ("subscription", "monthly", "recurring")) and all(
                "month" not in t.name.lower() for t in pricing.tiers):
            issues.append("Lean Canvas revenue streams mention a subscription, pricing proposes one-time tiers.")
        if any(t.price_usd == 0 for t in pricing.tiers) and "free" not in rev:
            issues.append("Pricing has a free tier not mentioned in the Lean Canvas revenue streams.")
    if store_page is not None and pricing is not None:
        prices = {f"{t.price_usd:g}" for t in pricing.tiers}
        found = set(re.findall(r"\$\s?(\d+(?:\.\d+)?)", f"{store_page.description} {' '.join(store_page.bullets)}"))
        for f in found:
            if f"{float(f):g}" not in prices:
                issues.append(f"Store page mentions ${f}, not an approved price ({', '.join(sorted(prices))}).")
    if store_page is not None and prd is not None:
        if prd.product_title.lower()[:20] not in (store_page.title + store_page.description).lower():
            issues.append(f"Store page title '{store_page.title}' differs from PRD product '{prd.product_title}'.")
    return issues

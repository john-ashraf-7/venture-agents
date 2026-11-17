"""Evidence Ledger: one row per atomic claim, with label, source, quote and checker."""
from __future__ import annotations

import json
import random
from typing import Any, Optional

from app.models import Claim, Label
from app.services.storage import conn


def _next_id(run_id: str) -> str:
    with conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM claims WHERE run_id=?", (run_id,)).fetchone()["n"]
    return f"C{n + 1}"


def add(claim: Claim) -> Claim:
    if not claim.id:
        claim.id = _next_id(claim.run_id)
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO claims (id, run_id, body) VALUES (?,?,?)",
                  (f"{claim.run_id}:{claim.id}", claim.run_id, claim.model_dump_json()))
    return claim


def new(run_id: str, **fields: Any) -> Claim:
    return add(Claim(id=_next_id(run_id), run_id=run_id, **fields))


def update(claim: Claim) -> None:
    add(claim)


def all_claims(run_id: str, artifact_id: Optional[str] = None) -> list[Claim]:
    with conn() as c:
        rows = c.execute("SELECT body FROM claims WHERE run_id=?", (run_id,)).fetchall()
    claims = [Claim.model_validate_json(r["body"]) for r in rows]
    if artifact_id:
        claims = [c for c in claims if c.artifact_id == artifact_id]
    return sorted(claims, key=lambda c: int(c.id[1:]) if c.id[1:].isdigit() else 0)


def get(run_id: str, claim_id: str) -> Optional[Claim]:
    with conn() as c:
        row = c.execute("SELECT body FROM claims WHERE id=?", (f"{run_id}:{claim_id}",)).fetchone()
    return Claim.model_validate_json(row["body"]) if row else None


def rewrite_unsupported(claim: Claim) -> Claim:
    """Unsupported claims become ASSUMPTION; never silently deleted."""
    claim.note = (claim.note or "") + f" Rewritten from {claim.label.value}: no source supports it."
    claim.label = Label.ASSUMPTION
    update(claim)
    return claim


def counts_for_gate(claim: Claim) -> bool:
    """Only SUPPORTED claims, checked by a different model family than the writer, count at a gate."""
    return (claim.label == Label.SUPPORTED and bool(claim.source_url) and claim.checked_by_family is not None
            and claim.checked_by_family != claim.writer_family)


def metrics(claims: list[Claim]) -> dict[str, Any]:
    factual = [c for c in claims if c.source_url or "Rewritten from" in (c.note or "")]
    supported_or_partial = [c for c in factual if c.label in (Label.SUPPORTED, Label.PARTIAL)]
    cited = [c for c in claims if c.source_url]
    precise = [c for c in cited if c.label == Label.SUPPORTED]
    by_label = {lbl.value: sum(1 for c in claims if c.label == lbl) for lbl in Label}
    total = len(claims) or 1
    return {
        "claims": len(claims),
        "citation_coverage": round(len(supported_or_partial) / len(factual), 3) if factual else None,
        "citation_precision": round(len(precise) / len(cited), 3) if cited else None,
        "by_label": by_label,
        "share_by_label": {k: round(v / total, 3) for k, v in by_label.items()},
    }


def spot_check(claims: list[Claim], n: int = 5, seed: int = 0) -> list[Claim]:
    supported = [c for c in claims if c.label == Label.SUPPORTED]
    rng = random.Random(seed)
    return rng.sample(supported, min(n, len(supported)))


def to_markdown(claims: list[Claim]) -> str:
    lines = ["| id | label | type | claim | source | quote |", "|---|---|---|---|---|---|"]
    for c in claims:
        q = (c.source_quote or "").replace("|", "/").replace("\n", " ")[:160]
        t = c.text.replace("|", "/").replace("\n", " ")
        lines.append(f"| {c.id} | {c.label.value} | {c.type} | {t} | {c.source_url or 'ASSUMPTION'} | {q} |")
    return "\n".join(lines)


def dump(run_id: str) -> str:
    return json.dumps([c.model_dump(mode="json") for c in all_claims(run_id)], indent=1)

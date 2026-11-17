"""Idea Scout: theory of value + 3-5 idea variants scored against each other (scores are ASSUMPTIONS)."""
from __future__ import annotations

from app.agents import base
from app.models import Brief, IdeaMatrix


def run(run_id: str, brief: Brief, lessons: list[str]) -> IdeaMatrix:
    return base.run(run_id, "idea_scout", "idea_scout", "find_opportunities", IdeaMatrix,
                    {"brief": brief, "lessons_from_earlier_runs": lessons},
                    instructions="Sharpen the founder's idea into a theory of value and 3-5 variants (the founder's "
                                 "original idea first). Variants must be digital products. Score each 1-5.")


def rank(matrix: IdeaMatrix) -> list[tuple[float, str]]:
    """Code ranking: demand + fit - regulatory burden - effort (all ASSUMPTION scores)."""
    out = []
    for v in matrix.variants:
        s = v.scores
        out.append((s.demand + s.founder_fit - 0.75 * s.regulatory_burden - 0.5 * s.effort, v.name))
    return sorted(out, reverse=True)

"""Interview Analyst: analyzes interview notes the FOUNDER pastes in (founder provenance)."""
from __future__ import annotations

from app.agents import base
from app.models import InterviewInsights


def run(run_id: str, notes: str, target_market: str) -> InterviewInsights:
    return base.run(run_id, "interview_analyst", "analyst", "analyze_interview_notes", InterviewInsights,
                    {"target_market": target_market, "founder_interview_notes": notes[:12000]},
                    instructions="Find patterns about past behaviour and spending. Quotes must be copied from the notes. "
                                 "Do not infer demand from compliments or future promises.")

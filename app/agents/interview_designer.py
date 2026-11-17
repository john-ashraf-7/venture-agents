"""Interview Designer: a Mom Test script. A code coach flags leading or hypothetical questions."""
from __future__ import annotations

import re

from app.agents import base
from app.models import Brief, InterviewScript, TheoryOfValue

LEADING = re.compile(r"\b(would you (buy|pay|use)|will you|do you (like|love)|wouldn'?t you|don'?t you think|"
                     r"isn'?t it|how much would you pay|would it be (useful|helpful)|if there (was|were) a)\b", re.I)


def flag_question(q: str) -> list[str]:
    issues = []
    if LEADING.search(q):
        issues.append("leading or hypothetical (asks about the future or seeks approval); ask about past behaviour instead")
    if re.search(r"\b(our|my) (product|app|idea|guide)\b", q, re.I):
        issues.append("mentions your idea; Mom Test questions are about their life, not your idea")
    return issues


def run(run_id: str, brief: Brief, tov: TheoryOfValue) -> InterviewScript:
    script = base.run(run_id, "interview_designer", "copywriter", "write_mom_test_script", InterviewScript,
                      {"target_market": brief.target_market, "theory_of_value": tov},
                      instructions="Write 6-10 Mom Test questions about past behaviour, current workarounds and money "
                                   "already spent. No questions about the future, no pitching.")
    bad = {q: flag_question(q) for q in script.questions}
    if any(bad.values()):
        script = base.run(run_id, "interview_designer", "copywriter", "revise_mom_test_script", InterviewScript,
                          {"script": script, "coach_flags": {q: f for q, f in bad.items() if f}},
                          instructions="Rewrite the flagged questions so they ask about past behaviour.")
        script.questions = [q for q in script.questions if not flag_question(q)] or script.questions
    return script

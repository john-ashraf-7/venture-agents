"""Demand Classifier: is a community quote a first-person statement of THE BRIEF'S problem?

Runs before a demand_signal is counted at the desk gate (role `demand_classifier`, config/models.yaml). A claim
counts only when both `first_person_problem` and `about_brief_problem` are true; rejects are logged with the
model's reason. Shared words alone (a SharePoint "list" question for a to-do app) do not make a signal.
"""
from __future__ import annotations

from typing import Optional

from app import llm
from app.config import prompt
from app.models import DemandClassification
from app.services import decision_log, reader


def classify(quote: str, *, problem: str, idea: str, thread_title: str = "", run_id: Optional[str] = None,
             url: str = "") -> DemandClassification:
    user = (f"BRIEF PROBLEM: {problem}\nBRIEF IDEA: {idea}\n"
            + (f"THREAD TITLE: {thread_title}\n" if thread_title else "")
            + "QUOTE:\n" + reader.wrap(quote))
    out = llm.call("demand_classifier", [{"role": "system", "content": prompt("demand_classifier")},
                                         {"role": "user", "content": user}], DemandClassification, run_id=run_id)
    if run_id:
        decision_log.append(run_id, "demand_classifier", "classify_demand" if counts(out) else "demand_rejected",
                            sources=[url] if url else [], model=llm.model_name("demand_classifier"),
                            first_person_problem=out.first_person_problem, about_brief_problem=out.about_brief_problem,
                            reason=out.reason[:300])
    return out


def counts(c: DemandClassification) -> bool:
    return c.first_person_problem and c.about_brief_problem

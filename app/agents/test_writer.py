"""Test Writer: writes the product test spec from the PRD only. It never sees the builder's output."""
from __future__ import annotations

from app.agents import base
from app.models import PRD, TestSpec


def run(run_id: str, prd: PRD) -> TestSpec:
    spec = base.run(run_id, "test_writer", "test_writer", "write_test_spec", TestSpec, {"prd": prd},
                    instructions="Write acceptance checks for the guide pack described by this PRD: the required "
                                 "headings (copy them exactly), minimum number of sections, minimum words per section, "
                                 "phrases that must never appear (income promises, fake reviews, urgency).")
    # The PRD's required sections are always required, whatever the test writer returned.
    for h in prd.required_sections:
        if h not in spec.required_headings:
            spec.required_headings.append(h)
    spec.min_words_per_section = min(spec.min_words_per_section, 80)
    for p in ["guaranteed income", "guaranteed results", "five-star", "limited time only"]:
        if p not in spec.forbidden_phrases:
            spec.forbidden_phrases.append(p)
    return spec

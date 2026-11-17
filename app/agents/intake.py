"""Intake: parses the founder's raw input into a Brief. Asks for missing info instead of assuming.

This is the only agent that ever sees the founder's raw text (context minimization).
"""
from __future__ import annotations

import re
from typing import Optional

from app.agents import base
from app.models import Brief, FounderInput


def _money(text: str) -> Optional[float]:
    m = re.search(r"(\d[\d,]*(\.\d+)?)\s*(k)?", text or "", re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v * 1000 if m.group(3) else v


def run(run_id: str, raw: FounderInput) -> Brief:
    brief = base.run(run_id, "intake", "intake", "parse_founder_brief", Brief, {"founder_input": raw},
                     instructions="Parse the founder input. Do not invent numbers: if budget or time is missing or "
                                  "vague, leave it null and add it to missing_info and questions_for_founder.")
    # Code cross-check: numbers must come from the founder's own text.
    if brief.budget_usd is not None and _money(raw.budget) is None:
        brief.missing_info.append("budget (not stated as a number)")
        brief.budget_usd = None
    if not raw.time.strip():
        brief.hours_per_week, brief.weeks_available = None, None
    return brief

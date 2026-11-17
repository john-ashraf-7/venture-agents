"""Method library: short cards in knowledge/*.md, chosen per agent by the `agents:` list in each card.

Cards are guidance on HOW to work (where evidence lives, the Mom Test, pricing practice). They are added to an
agent's system prompt under a "not evidence" heading and logged by id; they never enter the Evidence Ledger.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "knowledge"


@lru_cache(maxsize=1)
def cards() -> list[dict]:
    out = []
    for p in sorted(ROOT.glob("*.md")):
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", p.read_text(encoding="utf-8"), re.S)
        if not m:
            continue
        meta = dict(re.findall(r"^(\w+):\s*(.*)$", m.group(1), re.M))
        agents = [a.strip() for a in meta.get("agents", "").strip("[]").split(",") if a.strip()]
        out.append({"id": meta.get("id", p.stem), "agents": agents, "source": meta.get("source", ""), "body": m.group(2).strip()})
    return out


def for_agent(agent: str) -> list[dict]:
    return [c for c in cards() if agent in c["agents"]]


def as_prompt(selected: list[dict]) -> str:
    if not selected:
        return ""
    return ("\n\n## Method notes (guidance on how to work; NOT evidence about any market, never cite them as a source)\n\n"
            + "\n\n".join(f"### {c['id']} (after {c['source']})\n{c['body']}" for c in selected))

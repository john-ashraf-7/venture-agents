"""Shared agent runner: prompt file + typed context -> llm.call -> decision log entry."""
from __future__ import annotations

import json
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel

from app import llm
from app.config import prompt
from app.services import cost, decision_log, events, knowledge

T = TypeVar("T", bound=BaseModel)


def ctx(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=1)
    return json.dumps(obj, indent=1, default=str)


def run(run_id: Optional[str], agent: str, role: str, action: str, schema: type[T], context: dict[str, Any],
        *, sources: Optional[list[str]] = None, instructions: str = "",
        check: Optional[Callable[[T], Optional[str]]] = None, check_retries: int = 1) -> T:
    """Run one agent step. `context` holds typed artifacts only (never the founder's raw text)."""
    if run_id:
        events.emit(run_id, "step", f"{agent}: {action} ...", agent=agent)
    notes = knowledge.for_agent(agent)
    system = (prompt(agent) or prompt(role)) + knowledge.as_prompt(notes)
    user = (instructions + "\n\n" if instructions else "") + "\n\n".join(f"## {k}\n{ctx(v)}" for k, v in context.items())
    out = llm.call(role, [{"role": "system", "content": system}, {"role": "user", "content": user}], schema, run_id=run_id,
                   check=check, check_retries=check_retries)
    if run_id:
        last = cost.last_call(run_id)
        decision_log.append(run_id, agent, action, sources=sources or [], model=llm.model_name(role),
                            cost=0.0, approved_by=None, role=role, tokens_in=last.get("tokens_in"),
                            tokens_out=last.get("tokens_out"), latency_s=last.get("latency_s"),
                            cache_hit=last.get("cache_hit"), ref_cost_usd=last.get("ref_cost_usd"),
                            knowledge_cards=[c["id"] for c in notes])
    return out

"""Interview rehearsal: the founder practises the Mom Test script on 3 SIMULATED personas built from the
brief's target-market fields. A coach flags leading or hypothetical questions. Persona answers are
stored as ASSUMPTION and never count as evidence."""
from __future__ import annotations

from app import llm
from app.agents import base
from app.agents.interview_designer import flag_question
from app.models import Brief, Label, PersonaReply, Personas, Provenance
from app.services import ledger
from app.services.storage import kv_get, kv_set


def personas(run_id: str, brief: Brief) -> Personas:
    cached = kv_get(run_id, "personas")
    if cached:
        return Personas.model_validate(cached)
    p = base.run(run_id, "rehearsal", "coach", "build_simulated_personas", Personas,
                 {"target_market": brief.target_market, "idea": brief.idea},
                 instructions="Create 3 different fictional interviewees from this target market. They are SIMULATED "
                              "practice partners, not real people; vary attitude (skeptical, busy, interested).")
    kv_set(run_id, "personas", p.model_dump())
    return p


def ask(run_id: str, brief: Brief, persona_index: int, question: str) -> dict:
    ps = personas(run_id, brief)
    persona = ps.personas[persona_index % 3]
    flags = flag_question(question)
    reply = base.run(run_id, "rehearsal", "coach", "simulated_persona_reply", PersonaReply,
                     {"persona_SIMULATED": persona, "question": question},
                     instructions="Answer in character, briefly and realistically. If the question asks about the "
                                  "future or what you would buy, answer vaguely and politely, as real people do.")
    c = ledger.new(run_id, text=f"SIMULATED persona {persona.name}: {reply.reply[:200]}", type="other",
                   label=Label.ASSUMPTION, provenance=Provenance.agent, artifact_id="rehearsal",
                   note="SIMULATED persona answer - never evidence")
    return {"label": "SIMULATED", "persona": persona.model_dump(), "reply": reply.reply, "coach_flags": flags,
            "stored_as": c.id + " (ASSUMPTION)"}

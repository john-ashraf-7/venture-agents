"""Orchestrator: a plain-code state machine. It owns phases, gates and every side effect.

Agents only return typed drafts/claims/options. Gate verdicts are computed in app/gates.py against
rules locked before evidence is gathered. The founder makes the final call at every gate.
The run plan is fixed from the parsed brief BEFORE any web content is read.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from app import approval, gates, llm
from app.agents import (builder, claim_checker, commercial, competitor, compliance, experiment_designer,
                        gate_explainer, idea_scout, intake, interview_designer, landing_page, lean_canvas,
                        market_researcher, planner, test_writer)
from app.agents import base as agent_base
from app.agents import demand_classifier
from app.commerce import delivery, payments, refunds
from app.config import EVALS_DIR, caps, data_dir, founder_mode, gate_definitions, profile, profile_name
from app.models import (PRD, Brief, Claim, ExperimentPlan, FounderInput, GuidePack, IdeaMatrix, Label, LeanCanvas,
                        MarketSummary, PlanEstimate, PolicyDrafts, PricingSheet, Provenance, StorePage, Verdict,
                        now_iso)
from app.services import cost, decision_log, events, guard, ledger, lessons, outbox, quality
from app.services.storage import conn, kv_get, kv_set

PHASES = {1: "Discover", 2: "Validate", 3: "Build", 4: "Commercial setup", 5: "Sell, deliver, get paid", 6: "Operate and learn"}
# Dependency map: a step may only start when every listed gate has a GO (or a founder override).
DEPENDS_ON = {2: ["desk_evidence"], 3: ["experiment"], 4: ["tests"], 5: ["commercial"], 6: ["launch"]}
GATE_PHASE = {"desk_evidence": 1, "experiment_plan": 2, "experiment": 2, "tests": 3, "commercial": 4, "launch": 5}
GATE_NEXT = {"desk_evidence": 2, "experiment": 3, "tests": 4, "commercial": 5, "launch": 6}
DEMAND_TYPES = ("demand_signal", "paying_competitor", "trend")


# ----------------------------------------------------------------- state ------------------
def load(run_id: str) -> dict[str, Any]:
    with conn() as c:
        row = c.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError(run_id)
    return json.loads(row["state"])


def save(st: dict[str, Any]) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO runs (id, created_at, state) VALUES (?,?,?)",
                  (st["id"], st["created_at"], json.dumps(st, default=str)))


def list_runs() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute("SELECT state FROM runs ORDER BY created_at DESC").fetchall()
    return [json.loads(r["state"]) for r in rows]


def update(run_id: str, **fields: Any) -> dict[str, Any]:
    st = load(run_id)
    st.update(fields)
    save(st)
    return st


def write(run_id: str, phase: int, step: str, name: str, content: str, ext: str = "md", *,
          guard_check: bool = False) -> Path:
    """Write an artifact as outputs/runs/<run>/phase<N>_<step>_<name>.<ext>; prior versions are kept."""
    st = load(run_id)
    ver = st.get("version", 1)
    fname = f"phase{phase}_{step}_{name}" + (f"_v{ver}" if ver > 1 else "") + f".{ext}"
    if guard_check:
        g = guard.check(content, run_id=run_id, context=f"final_artifact:{fname}")
        if not g.allowed:
            content = f"[WITHHELD BY POLICY GUARD: {g.reason}]\n"
    path = decision_log.run_dir(run_id) / fname
    path.write_text(content, encoding="utf-8")
    st = load(run_id)
    st.setdefault("artifacts", {})[f"phase{phase}_{step}_{name}"] = fname
    save(st)
    decision_log.append(run_id, "orchestrator", "write_output", sources=[], model=None, file=fname, tier=0)
    return path


def artifact(run_id: str, key: str, model: Any) -> Any:
    data = kv_get(run_id, f"artifact:{key}")
    return model.model_validate(data) if data is not None else None


def keep(run_id: str, key: str, obj: Any) -> None:
    kv_set(run_id, f"artifact:{key}", obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj)


# ----------------------------------------------------------------- run lifecycle ----------
def _thread(run_id: str, fn: Callable[[str], None]) -> threading.Thread:
    def target() -> None:
        try:
            events.check_kill()
            fn(run_id)
        except events.Cancelled as e:
            update(run_id, status="killed", error=str(e))
            events.emit(run_id, "killed", str(e))
        except Exception as e:  # typed failure surfaced to the founder, never hidden
            lessons.add(run_id, "error", f"{type(e).__name__}: {e}"[:300])
            update(run_id, status="error", error=f"{type(e).__name__}: {e}")
            decision_log.append(run_id, "orchestrator", "error", reason=f"{type(e).__name__}: {str(e)[:300]}")
            events.emit(run_id, "error", f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])
    t = threading.Thread(target=target, daemon=True)
    t.start()
    return t


def brief_hash(raw: FounderInput) -> str:
    return hashlib.sha256(raw.model_dump_json().encode()).hexdigest()[:12]


def start(raw: FounderInput, *, background: bool = True) -> dict[str, Any]:
    """Create a run. Founder inputs pass the Policy Guard; excluded product types stop at intake."""
    run_id = "run_" + now_iso().replace(":", "").replace("-", "")[:15] + "_" + uuid.uuid4().hex[:4]
    st = {"id": run_id, "created_at": now_iso(), "status": "created", "phase": 1, "version": 1,
          "profile": profile_name(), "founder_mode": founder_mode(), "brief_hash": brief_hash(raw),
          "founder_input": raw.model_dump(), "gates": {}, "artifacts": {}, "awaiting": None, "timings": {}}
    save(st)
    cost.start(run_id)
    decision_log.append(run_id, "founder", "submit_brief", initiated_by="founder", approved_by=None)
    text = " ".join(raw.model_dump().values())
    g = guard.check(text, run_id=run_id, context="founder_input")
    # skills are left out: a founder who is a nurse or a law student may still build an allowed product
    excluded = guard.excluded_type(f"{raw.idea}. {raw.target_market}. {raw.values}")
    if not g.allowed or excluded:
        reason = g.reason if not g.allowed else f"Excluded product type: {excluded}. This system does not build physical goods, financial/crypto products, or health/legal advice products."
        update(run_id, status="blocked", error=reason)
        decision_log.append(run_id, "policy_guard", "block_at_intake", reason=reason, outcome="stop")
        write(run_id, 1, "step1", "intake_blocked", f"# Intake blocked\n\n{reason}\n")
        events.emit(run_id, "blocked", reason)
        return load(run_id)
    if background:
        _thread(run_id, phase1)
    else:
        phase1(run_id)
    return load(run_id)


def kill() -> dict[str, Any]:
    events.KILL.set()
    n = outbox.cancel_all_pending()
    for st in list_runs():
        if st["status"] in ("running", "awaiting_founder", "created"):
            st["status"] = "killed"
            save(st)
            decision_log.append(st["id"], "kill_switch", "stop_all_agents", approved_by="founder")
    return {"killed": True, "outbox_cancelled": n}


def unkill() -> None:
    events.KILL.clear()


# ----------------------------------------------------------------- gates (shared) ---------
def pause_at_gate(run_id: str, gate: str, result: gates.GateResult, locked_rule: dict[str, Any], phase: int,
                  extra_md: str = "") -> None:
    explanation = gate_explainer.explain(run_id, result, locked_rule)
    devil = gate_explainer.devils_advocate(run_id, result)
    opts = gates.options_for(result)
    if founder_mode() == "evaluate":
        explanation = gates.first_sentence(explanation) + " " + "; ".join(result.reasons)
    rec = {"gate": gate, "result": result.to_dict(), "explanation": explanation, "devils_advocate": devil.model_dump(),
           "options": opts, "locked_rule": locked_rule, "decision": None}
    st = load(run_id)
    st["gates"][gate] = rec
    st["awaiting"] = {"gate": gate, "phase": phase}
    st["status"] = "awaiting_founder"
    save(st)
    decision_log.append(run_id, "gate", f"{gate}_gate", sources=[], model=None, cost=0, approved_by=None,
                        outcome=result.verdict.value.lower(), recommendation=result.verdict.value, state=result.state,
                        options_considered=[o["choice"] for o in opts], initiated_by="agent",
                        checks=[{"name": c.name, "value": c.value, "threshold": c.threshold, "passed": c.passed} for c in result.checks])
    write(run_id, phase, "gate", gate, gate_markdown(rec) + extra_md)
    events.emit(run_id, "gate", f"{gate} gate: {result.verdict.value}", gate=gate, verdict=result.verdict.value)


def gate_markdown(rec: dict[str, Any]) -> str:
    r = rec["result"]
    lines = [f"# Gate: {rec['gate']}", "", f"**{gates.first_sentence(rec['explanation'])}**", "",
             f"- Verdict computed by code: **{r['verdict']}**" + (f" (state: {r['state']})" if r.get("state") else ""),
             f"- Computed at: {r['computed_at']}", "", "## Locked rule", "", "```json",
             json.dumps(rec["locked_rule"], indent=1), "```", "", "## Checks", "", "| check | value | threshold | pass |", "|---|---|---|---|"]
    for c in r["checks"]:
        lines.append(f"| {c['name']} | {c['value']} | {c['threshold']} | {c['passed']} |")
    lines += ["", "## Explanation", "", rec["explanation"], "", "## Devil's advocate", "",
              f"- Bull case: {rec['devils_advocate']['bull_case']}", f"- Bear case: {rec['devils_advocate']['bear_case']}",
              "", "## Options", ""]
    for o in rec["options"]:
        tag = " (recommended)" if o["recommended"] else ""
        tag += " (weakest evidence)" if o["weakest_evidence"] else ""
        lines.append(f"- **{o['choice']}**{tag}: {o['label']}. Evidence: {o['evidence']}. Risk: {o['risk']}")
    if rec.get("decision"):
        d = rec["decision"]
        lines += ["", "## Founder decision", "", f"- Choice: **{d['choice']}** (recommendation was {d['recommendation']})",
                  f"- Override: {d['override']}", f"- Reason: {d.get('reason') or '-'}", f"- Decided at: {d['decided_at']}"]
    return "\n".join(lines) + "\n"


def decide(run_id: str, gate: str, choice: str, reason: str = "", payload: Optional[dict[str, Any]] = None,
           background: bool = True) -> dict[str, Any]:
    st = load(run_id)
    rec = st["gates"].get(gate)
    if not rec or (st.get("awaiting") or {}).get("gate") != gate:
        raise approval.ApprovalError(f"Gate {gate} is not waiting for a decision.")
    recommendation = Verdict(rec["result"]["verdict"])
    d = approval.decide(run_id, gate, recommendation, choice, reason, rec["options"])
    d.pop("log", None)
    rec["decision"] = d
    st["awaiting"] = None
    st["status"] = "running"
    save(st)
    phase = GATE_PHASE[gate]
    write(run_id, phase, "gate", gate, gate_markdown(rec))
    choice_v = Verdict(choice)
    if recommendation == Verdict.STOP:
        stop_memo(run_id, gate, rec, d)
    nxt: Optional[Callable[[str], None]] = None
    if gate == "experiment_plan":
        nxt = phase2_launch_test if choice_v == Verdict.GO else (phase2 if choice_v == Verdict.REPEAT else None)
    elif choice_v == Verdict.GO:
        nxt = PHASE_FN[GATE_NEXT[gate]]
    elif choice_v in (Verdict.REPEAT, Verdict.PIVOT_BACK):
        if gate == "desk_evidence" or choice_v == Verdict.PIVOT_BACK:
            niche = (payload or {}).get("niche", "").strip()
            st = load(run_id)
            st["version"] = st.get("version", 1) + 1
            if niche:
                st["founder_input"]["target_market"] = niche
                decision_log.append(run_id, "founder", "pivot_niche", approved_by="founder", initiated_by="founder",
                                    provenance=Provenance.founder.value, niche=niche)
            save(st)
            nxt = phase1
        elif gate == "experiment":
            nxt = recheck_experiment
        else:
            nxt = PHASE_FN[phase]
    if nxt is None:
        final = {"STOP": "stopped", "PARK": "parked"}.get(choice_v.value, "parked")
        update(run_id, status=final)
        finish(run_id)
        events.emit(run_id, "done", f"Run {final} by founder decision.")
        return load(run_id)
    if background:
        _thread(run_id, nxt)
    else:
        nxt(run_id)
    return load(run_id)


def reconsider(run_id: str, gate: str, message: str) -> dict[str, Any]:
    st = load(run_id)
    rec = st["gates"][gate]
    out = approval.reconsider(Verdict(rec["result"]["verdict"]), message)
    decision_log.append(run_id, "gate", f"reconsider_{gate}", initiated_by="founder", recommendation=out["recommendation"],
                        changed=False, message=message[:200])
    return out


def stop_memo(run_id: str, gate: str, rec: dict[str, Any], d: dict[str, Any]) -> None:
    st = load(run_id)
    runs_same = [r for r in list_runs() if r.get("brief_hash") == st.get("brief_hash")]
    runs_same.sort(key=lambda r: r["created_at"])
    n = next((i + 1 for i, r in enumerate(runs_same) if r["id"] == run_id), len(runs_same))
    body = [f"# STOP memo ({gate} gate)", "", f"Recommendation: STOP.", "",
            f"This is run {n} of {len(runs_same)} for this brief (every run is kept in outputs/runs/).", "",
            "## Why", ""] + [f"- {x}" for x in rec["result"]["reasons"]] + [
            "", "## Explanation", "", rec["explanation"], "", "## Founder decision", "",
            f"- Choice: {d['choice']}", f"- Override: {d['override']}", f"- Override reason: {d.get('reason') or '-'}",
            "", "## What would change our mind", "", str(rec["locked_rule"].get("change_our_mind", "-"))]
    write(run_id, GATE_PHASE[gate], "gate", f"{gate}_stop_memo", "\n".join(body) + "\n")


def finish(run_id: str) -> None:
    s = cost.write(run_id, decision_log.run_dir(run_id) / "cost.json")
    decision_log.append(run_id, "cost_meter", "cost_per_run", cost=s["cost_usd"], ref_cost_usd=s["ref_cost_usd"],
                        tokens_in=s["tokens_in"], tokens_out=s["tokens_out"], wall_clock_s=s["wall_clock_s"])


# ----------------------------------------------------------------- Phase 1 ----------------
FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|my|me|we|we're|our|us)\b", re.I)


def on_community_site(url: str, domains: list[str]) -> bool:
    """Suffix match on the host, plus an optional path prefix (e.g. producthunt.com/discussions)."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    host, path = u.netloc.lower().removeprefix("www."), u.path.lower().lstrip("/")
    for d in domains:
        dh, _, dp = d.lower().partition("/")
        if (host == dh or host.endswith("." + dh)) and path.startswith(dp):
            return True
    return False


def community_demand(quote: str, page: dict[str, Any], rule: dict[str, Any]) -> bool:
    """A demand signal: a community site from the locked rule, a first-person quote, and a date on that quote."""
    if not on_community_site(page["url"], rule.get("community_domains", [])):
        return False
    if not FIRST_PERSON.search(quote or ""):
        return False
    norm = market_researcher.normalize
    return any(ps.get("date") and _date_on_source(ps["date"], page)
               and (norm(ps.get("quote", "")) in norm(quote) or norm(quote) in norm(ps.get("quote", "")))
               for ps in page["extract"].get("problem_statements", []))


def _date_on_source(date: str, page: dict[str, Any]) -> bool:
    """A date from a community API is API data; any other date (a model read the page, e.g. Tavily raw content,
    which carries no dates in practice) must appear in the page text itself."""
    return bool(page.get("provider")) or market_researcher.normalize(str(date)) in market_researcher.normalize(page.get("text", ""))


def _off_topic_demand(run_id: str, d: Any, page: dict[str, Any], problem: str, idea: str) -> Optional[str]:
    """Why a community demand quote does not count for THIS brief (None when it counts). The demand_classifier
    role must say the quote is a first-person problem AND the brief's problem; a failed call does not count."""
    try:
        c = demand_classifier.classify(d.source_quote, problem=problem, idea=idea, thread_title=page.get("thread_title", ""),
                                       run_id=run_id, url=page["url"])
    except llm.LLMError as e:
        decision_log.append(run_id, "demand_classifier", "demand_rejected", sources=[page["url"]], model=e.model,
                            reason=f"classifier failed: {e.detail[:150]}")
        return f"classifier failed ({e.detail[:80]})"
    return None if demand_classifier.counts(c) else (c.reason or "not a first-person statement of the brief's problem")


COMPETITOR_PURPOSES = ("competitors", "alternatives", "pricing", "pricing_fallback")
PRICE = re.compile(r"(?:[$€£]|\b(?:usd|eur|gbp|egp)\b)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:[$€£]|\b(?:usd|eur|gbp|egp)\b)", re.I)


def priced_competitor(quote: str, page: dict[str, Any]) -> bool:
    """A paying competitor needs a non-zero price in the quote, on a page found by a competitor or pricing search
    (a page fetched for demand research may sell anything)."""
    if page.get("purpose") not in COMPETITOR_PURPOSES:
        return False
    amounts = [float((a or b).replace(",", ".")) for a, b in PRICE.findall(quote or "")]
    return any(x > 0 for x in amounts)


def desk_rule(brief: Brief) -> dict[str, Any]:
    g = gate_definitions()
    d = dict(g["desk_gate"])
    d["change_our_mind"] = d["change_our_mind"].format(**d)
    d["definitions"] = g["definitions"]
    d["brief_idea"] = brief.idea
    d["counting"] = "distinct (source_url, type) SUPPORTED claims of types demand_signal, paying_competitor, trend, checked by a different model family"
    return d


def phase1(run_id: str) -> None:
    t0 = cost.time.time()
    st = update(run_id, status="running", phase=1)
    ver = st.get("version", 1)
    events.emit(run_id, "phase", f"Phase 1 - Discover (v{ver})")
    raw = FounderInput(**st["founder_input"])
    brief = intake.run(run_id, raw)
    keep(run_id, "brief", brief)
    write(run_id, 1, "step1", "brief", "# Parsed brief\n\n```json\n" + brief.model_dump_json(indent=1) + "\n```\n\n"
          + ("## Questions for the founder (missing info, not assumed)\n\n" + "\n".join(f"- {q}" for q in brief.questions_for_founder) if brief.questions_for_founder else ""))

    # Lock the desk-gate rule BEFORE any research runs.
    rule = desk_rule(brief)
    lock = gates.lock_rule(run_id, f"desk_evidence_v{ver}", rule)
    decision_log.append(run_id, "gate", "lock_desk_gate_rule", sha256=lock["sha256"], locked_at=lock["locked_at"])
    write(run_id, 1, "step2", "gate_rule_locked", json.dumps(lock, indent=1), "json")

    # Plan-then-execute: queries and estimates come from the parsed brief only.
    past = lessons.relevant(brief.idea + " " + brief.target_market)
    plan = planner.estimate(run_id, brief, past)
    keep(run_id, "plan", plan)
    hours_avail = (brief.hours_per_week * brief.weeks_available) if brief.hours_per_week and brief.weeks_available else None
    planned = market_researcher.plan_queries(run_id, plan.search_terms, brief.idea)
    tight = (brief.budget_usd is not None and plan.cost_high_usd > brief.budget_usd) or (
        hours_avail is not None and plan.hours_high > hours_avail)
    write(run_id, 1, "step3", "research_plan", "\n".join([
        "# Research plan (fixed before any web page was read)", "",
        f"- Effort estimate (ASSUMPTION): {plan.hours_low:.0f}-{plan.hours_high:.0f} hours (available: {hours_avail or 'unknown'})",
        f"- Cost estimate (ASSUMPTION): ${plan.cost_low_usd:,.0f}-${plan.cost_high_usd:,.0f} (budget: {brief.budget_usd or 'unknown'})",
        *([f"- Baseline used (ASSUMPTION, config/product_type_baselines.yaml): {plan.baseline['label']}: "
           f"{plan.baseline['hours'][0]:g}-{plan.baseline['hours'][1]:g} hours, ${plan.baseline['cost_usd'][0]:g}-${plan.baseline['cost_usd'][1]:g}",
           f"- Model's own estimate (ASSUMPTION): {plan.model_estimate['hours_low']:g}-{plan.model_estimate['hours_high']:g} hours, "
           f"${plan.model_estimate['cost_low_usd']:g}-${plan.model_estimate['cost_high_usd']:g}"
           + (f"; adjustment reason: {plan.adjustment_reason}" if plan.adjustment_reason else "; no adjustment reason given"),
           f"- Clamped in code: {'yes' if plan.clamped else 'no'} (allowed {plan.baseline['allowed_hours'][0]:g}-{plan.baseline['allowed_hours'][1]:g} hours, "
           f"${plan.baseline['allowed_cost_usd'][0]:g}-${plan.baseline['allowed_cost_usd'][1]:g})"] if plan.baseline else []),
        f"- Required skills (ASSUMPTION): {', '.join(plan.required_skills)}",
        f"- Founder capacity: {'TIGHT - scope reduced and guardrails tightened' if tight else 'fits or unknown'}",
        f"- Caps ({profile_name()}): {caps()}", "", "## Search terms (keywords from the planner)", "",
        f"```json\n{plan.search_terms.model_dump_json(indent=1)}\n```", "",
        "## Queries (built in code from templates, linted)", ""] + [f"- [{p}] {q}" for p, q in planned]
        + ["", "Second-pass queries (`alternatives to` / `pricing` for the first competitor found) are added after reading "
           "and logged in the decision log with the competitor name's web provenance."]
        + (["", "## Lessons from earlier runs (relevance-filtered)", ""] + [f"- {l}" for l in past] if past else [])))

    ideas = idea_scout.run(run_id, brief, past)
    events.emit(run_id, "step", f"{len(ideas.variants)} idea variants")

    research = market_researcher.gather(run_id, planned)
    # second pass: the first competitor named on a product page gets an "alternatives" and a "pricing" query
    top = next((p["extract"].get("product_name") for p in research["pages"] if p.get("purpose") in COMPETITOR_PURPOSES
                and p["extract"].get("page_kind") == "product" and p["extract"].get("product_name")), None)
    if top:
        decision_log.append(run_id, "market_researcher", "second_pass_competitor", competitor=top,
                            provenance=Provenance.web.value)
        more = market_researcher.gather(run_id, market_researcher.plan_queries(
            run_id, plan.search_terms, brief.idea, {"alternatives": top, "pricing": top}),
            skip={p["url"] for p in research["pages"]})
        research = {"searches": research["searches"] + more["searches"], "pages": research["pages"] + more["pages"]}
        priced = any(p.get("purpose") == "pricing" and not market_researcher.is_snippet(p)
                     and (p["extract"].get("price_text") or p.get("structured_prices")) for p in more["pages"])
        if not priced:  # one extra query; its snippets stay PARTIAL unless a fetched page confirms the price
            fb = market_researcher.gather(run_id, market_researcher.plan_queries(
                run_id, plan.search_terms, brief.idea, {"pricing_fallback": top}),
                skip={p["url"] for p in research["pages"]})
            research = {"searches": research["searches"] + fb["searches"], "pages": research["pages"] + fb["pages"]}
    # community posts from official APIs (HN, Stack Exchange, Reddit with keys): quote and date from the API, no LLM read
    research["pages"] += market_researcher.community_pages(run_id, plan.search_terms, skip={p["url"] for p in research["pages"]})
    pages = research["pages"]
    src_md = ["# Sources", ""]
    for s in research["searches"]:
        src_md += [f"## Query: {s['query']} ({s['note']})", ""] + [f"- {r['title']} - {r['url']}" for r in s["results"]] + [""]
    src_md += ["## Pages read (isolated reader)", ""] + [f"- {p['url']} (retrieved {p['retrieved_at']}, {p['origin']})"
                                                          for p in pages if not market_researcher.is_snippet(p)]
    snips = [p for p in pages if market_researcher.is_snippet(p)]
    if snips:
        src_md += ["", "## Search snippets used (page failed or had no target fields; claims are PARTIAL, never counted)", ""] + [
            f"- {p['url']} ({p['purpose']})" for p in snips]
    write(run_id, 1, "step4", "sources", "\n".join(src_md))

    # Claims -> code quote check -> cross-family checker -> ledger
    drafts = market_researcher.extract_claims(run_id, brief, pages)
    by_url = {p["url"]: p for p in pages}
    writer_family = llm.family_of("claim_extractor")
    check_scope = profile().get("check_scope", "gate")
    to_check: list[Claim] = []
    for d in drafts.claims:
        page = by_url.get(d.source_url)
        vendor_copy = d.type == "demand_signal" and page and not community_demand(d.source_quote, page, lock["rule"])
        not_a_price = d.type == "paying_competitor" and page and not priced_competitor(d.source_quote, page)
        off_topic = None
        if d.type == "demand_signal" and page and not vendor_copy:
            off_topic = _off_topic_demand(run_id, d, page, plan.search_terms.problem, brief.idea)
        if vendor_copy or not_a_price or off_topic:
            d.type = "other"
        c = ledger.new(run_id, text=d.text, type=d.type, label=Label.PARTIAL, source_url=d.source_url if page else None,
                       source_quote=d.source_quote, retrieved_at=page["retrieved_at"] if page else None,
                       writer_family=writer_family, provenance=Provenance.web, artifact_id=f"phase1_market_v{ver}")
        if vendor_copy:
            c.note = "Vendor or article copy, not a person describing the problem: not a demand signal."
        if not_a_price:
            c.note = "Not a paying competitor: no non-zero price, or the page was not found by a competitor/pricing search."
        if off_topic:
            c.note = f"Not a demand signal for this brief (demand classifier): {off_topic}"
        via = ""
        if page and (page.get("provider") or page.get("via")):
            via = " " + (f"via {page['provider']} API" if page.get("provider") else f"via {page['via']}")
            c.note = ((c.note or "") + via).strip()
        if not page:
            ledger.rewrite_unsupported(c)
        elif market_researcher.is_snippet(page):
            c.note = "snippet only" + via
            c.label = Label.UNSUPPORTED if not market_researcher.quote_in_source(d.source_quote, page["text"]) else Label.PARTIAL
            if c.label == Label.UNSUPPORTED:
                ledger.rewrite_unsupported(c)
            else:
                ledger.update(c)
        elif not market_researcher.quote_in_source(d.source_quote, page["text"]):
            c.note = "Quote not found in fetched source text." + via
            c.label = Label.UNSUPPORTED
            ledger.rewrite_unsupported(c)
        elif check_scope == "all" or d.type in DEMAND_TYPES:
            to_check.append(c)
        else:
            c.label = Label.ASSUMPTION
            c.note = c.note or "Not checked in demo-fast (does not feed the gate)."
            ledger.update(c)
    for c in to_check:
        events.check_kill()
        try:
            claim_checker.check(run_id, c, by_url[c.source_url]["text"])
        except llm.LLMError as e:
            c.note = f"checker failed: {e.detail[:100]}"
            ledger.rewrite_unsupported(c)
    claims = ledger.all_claims(run_id, f"phase1_market_v{ver}")
    unsupported = sum(1 for c in claims if "Rewritten from" in (c.note or ""))
    if claims and unsupported / len(claims) > 0.5:
        lessons.add(run_id, "checker", f"Over half of extracted claims were unsupported for '{brief.idea[:60]}'; prefer pages with explicit prices and dated posts.")

    comp = competitor.run(run_id, brief, pages)
    comp.rows = [r for r in comp.rows if r.url in by_url]
    keep(run_id, "competitors", comp)
    cq = compliance.quick(run_id, brief)
    flag_ids = []
    for f in cq.flags:
        fc = ledger.new(run_id, text=f"Compliance: {f.issue} ({f.reason})", type="compliance", label=Label.ASSUMPTION,
                        provenance=Provenance.agent, artifact_id=f"phase1_compliance_v{ver}", note="blocking" if f.blocking else "")
        flag_ids.append(fc.id)
    for v in ideas.variants:
        v.regulatory_claim_ids = flag_ids
    keep(run_id, "ideas", ideas)
    ranking = idea_scout.rank(ideas)
    opp = ["# Opportunities (Phase 1, step 6)", "", "## Theory of value (ASSUMPTION: model reasoning, not sourced)", "",
           f"- Who (ASSUMPTION): {ideas.theory_of_value.who}", f"- Problem (ASSUMPTION): {ideas.theory_of_value.problem}",
           f"- Why now (ASSUMPTION): {ideas.theory_of_value.why_now}", f"- Why us (ASSUMPTION): {ideas.theory_of_value.why_us}", "",
           "## Idea variants (scores are ASSUMPTION; regulatory burden cites compliance claims)", "",
           "| variant | buyer | demand | fit | regulatory burden | effort | rank score | regulatory claims |", "|---|---|---|---|---|---|---|---|"]
    rank_map = {n: s for s, n in ranking}
    for v in ideas.variants:
        s = v.scores
        opp.append(f"| {v.name}: {v.one_liner} | {v.buyer} | {s.demand} | {s.founder_fit} | {s.regulatory_burden} | {s.effort} | {rank_map[v.name]:.2f} | {', '.join(v.regulatory_claim_ids) or '-'} |")
    write(run_id, 1, "step6", "opportunities", "\n".join(opp) + "\n", guard_check=True)

    all_c = ledger.all_claims(run_id)
    summary = agent_base.run(run_id, "market_researcher", "analyst", "write_market_brief", MarketSummary,
                             {"idea": brief.idea, "target_market": brief.target_market,
                              "ledger_claims": [{"id": c.id, "label": c.label.value, "text": c.text} for c in all_c]},
                             sources=[c.source_url for c in all_c if c.source_url],
                             instructions="Summarize the market in 4-6 sentences. Cite claim ids like [C2] for every factual "
                                          "statement, only SUPPORTED or PARTIAL claims. Mark anything else 'ASSUMPTION:'.")
    q = quality.score(summary, claims)
    qcfg = gate_definitions()["quality"]
    revisions = 0
    valid_ids = {c.id for c in all_c if c.label in (Label.SUPPORTED, Label.PARTIAL)}
    while revisions < qcfg["max_revisions"]:
        cited = set(re.findall(r"\[(C\d+)\]", summary.summary))
        bad = sorted(cited - valid_ids)
        if q["score"] >= qcfg["min_score"] and not bad:
            break
        revisions += 1
        summary = agent_base.run(run_id, "market_researcher", "analyst", f"revise_market_brief_{revisions}", MarketSummary,
                                 {"previous": summary, "checker_findings": {"invalid_citations": bad, "quality": q},
                                  "valid_claims": [{"id": c.id, "label": c.label.value, "text": c.text} for c in all_c]},
                                 instructions="Revise: cite only valid SUPPORTED/PARTIAL claim ids; mark the rest 'ASSUMPTION:'.")
        q = quality.score(summary, claims)
    q["revisions"] = revisions
    if q["score"] < qcfg["min_score"]:
        q["escalated_to_founder"] = True
    keep(run_id, "market_summary", summary)
    write(run_id, 1, "step5", "evidence_ledger", "# Evidence ledger\n\n" + json.dumps(ledger.metrics(all_c), indent=1)
          + "\n\n" + ledger.to_markdown(all_c) + "\n")
    write(run_id, 1, "step7", "market_brief", "\n".join([
        "# Market brief", "", summary.summary, "", "## Segments (ASSUMPTION unless cited)", ""] + [f"- {s}" for s in summary.segments]
        + ["", "## Quality", "", "```json", json.dumps(q, indent=1), "```", "",
           "Claims without a SUPPORTED source are labeled ASSUMPTION in the ledger (step 5)."]) + "\n", guard_check=True)
    comp_md = ["# Competitors", "", "| name | url | price (from page) | verified price | direct | why |", "|---|---|---|---|---|---|"]
    paying_urls = {c.source_url for c in all_c if c.type == "paying_competitor" and ledger.counts_for_gate(c)}
    for r in comp.rows:
        comp_md.append(f"| {r.name} | {r.url} | {r.price_text or '-'} | {'yes' if r.url in paying_urls else 'no'} | {r.is_direct} | {r.direct_reason} |")
    write(run_id, 1, "step8", "competitors", "\n".join(comp_md) + "\n")
    write(run_id, 1, "step9", "compliance_quick", "# Compliance quick check\n\n" + compliance.DISCLAIMER + "\n\n"
          + "\n".join(f"- [{'BLOCKING' if f.blocking else 'note'}] {f.issue}: {f.reason}" for f in cq.flags)
          + f"\n\nRegulatory burden (ASSUMPTION): {cq.regulatory_burden}/5\n")
    script = interview_designer.run(run_id, brief, ideas.theory_of_value)
    keep(run_id, "interview_script", script)
    write(run_id, 1, "step10", "interview_script", "# Mom Test interview script\n\nGoal: " + script.goal + "\n\n"
          + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(script.questions)) + "\n\n## Avoid\n\n"
          + "\n".join(f"- {a}" for a in script.avoid) + "\n", guard_check=True)

    # Desk gate: counted by code from the ledger.
    # demand_signal claims that survived to here passed community_demand() at creation (community site,
    # first-person, dated); anything else was relabelled "other" and does not count
    counting = {(c.source_url, c.type) for c in all_c if c.type in DEMAND_TYPES and ledger.counts_for_gate(c)
                and (c.type != "trend" or re.search(r"\d", c.source_quote or ""))}
    # a trend says where a market is moving, not that anyone wants this product: at most one counts
    trends = sorted(k for k in counting if k[1] == "trend")
    counting -= set(trends[1:])
    missing = [s for s in plan.required_skills if not any(s.lower() in k.lower() or k.lower() in s.lower() for k in brief.skills)]
    ev = gates.DeskEvidence(
        demand_signals=len(counting), paying_competitors=len(paying_urls),
        direct_competitors=sum(1 for r in comp.rows if r.is_direct), blocking_flags=sum(1 for f in cq.flags if f.blocking),
        cost_high_usd=plan.cost_high_usd, budget_usd=brief.budget_usd, hours_high=plan.hours_high,
        hours_available=hours_avail, missing_skills=missing[:3] if len(missing) > len(plan.required_skills) / 2 else [])
    result = gates.desk_gate(lock["rule"], ev)
    st = load(run_id)
    st["timings"][f"phase1_to_gate_v{ver}_s"] = round(cost.time.time() - t0, 1)
    save(st)
    pause_at_gate(run_id, "desk_evidence", result, lock["rule"], 1,
                  extra_md=f"\n## Timing\n\nIntake to verdict: {round(cost.time.time() - t0, 1)} s ({profile_name()}).\n")
    finish(run_id)


# ----------------------------------------------------------------- Phase 2 ----------------
def _approval_gate(run_id: str, gate: str, phase: int, summary: list[str], problems: list[str]) -> None:
    verdict = Verdict.GO if not problems else Verdict.REPEAT
    result = gates.GateResult(gate, verdict, [gates.Check("issues_found", len(problems), "== 0", not problems)],
                              (problems or ["Ready for founder approval."]) + summary)
    rule = {"type": "founder_approval", "rule": "The founder approves or rejects; nothing outward happens before approval."}
    pause_at_gate(run_id, gate, result, rule, phase)


def phase2(run_id: str) -> None:
    update(run_id, status="running", phase=2)
    events.emit(run_id, "phase", "Phase 2 - Validate")
    brief, ideas = artifact(run_id, "brief", Brief), artifact(run_id, "ideas", IdeaMatrix)
    claims = ledger.all_claims(run_id)
    canvas = lean_canvas.run(run_id, brief, ideas, claims)
    keep(run_id, "canvas", canvas)
    lab = lean_canvas.labeled(canvas)
    md = ["# Lean Canvas", "", "Items without a SUPPORTED claim are ASSUMPTION.", ""]
    for box, items in lab.items():
        md += [f"## {box.replace('_', ' ').title()}", ""] + [f"- [{i['label']}{' ' + i['claim_id'] if i['claim_id'] else ''}] {i['text']}" for i in items] + [""]
    write(run_id, 2, "step1", "lean_canvas", "\n".join(md), guard_check=True)
    risk = lean_canvas.riskiest(canvas)
    keep(run_id, "riskiest", {"items": risk})
    write(run_id, 2, "step2", "riskiest_assumptions", "# Riskiest assumptions (impact x uncertainty)\n\n| rank | assumption | impact | uncertainty | risk |\n|---|---|---|---|---|\n"
          + "\n".join(f"| {r['rank']} | {r['text']} | {r['impact']} | {r['uncertainty']} | {r['risk']} |" for r in risk) + "\n")
    plan = experiment_designer.run(run_id, brief, risk, claims)
    keep(run_id, "experiment_plan", plan)
    write(run_id, 2, "step3", "experiment_plan", "# Experiment plan (proposed; locks on founder approval)\n\n```json\n"
          + plan.model_dump_json(indent=1) + "\n```\n")
    problems = []
    if plan.threshold_source == "ASSUMPTION":
        problems_note = "Threshold is an ASSUMPTION (no sourced benchmark)."
    else:
        problems_note = f"Threshold from benchmark claim {plan.benchmark_claim_id}."
    _approval_gate(run_id, "experiment_plan", 2,
                   [f"Test: {plan.signups_threshold} sign-ups in {plan.window_days} days, min {plan.min_visitors} visitors. {problems_note}",
                    f"Tests the riskiest assumption first: {plan.assumption_tested}"], problems)


def phase2_launch_test(run_id: str) -> None:
    update(run_id, status="running", phase=2)
    brief, canvas, plan = artifact(run_id, "brief", Brief), artifact(run_id, "canvas", LeanCanvas), artifact(run_id, "experiment_plan", ExperimentPlan)
    d = gate_definitions()["experiment_gate"]
    rule = {"signups_threshold": plan.signups_threshold, "min_visitors": plan.min_visitors, "window_days": plan.window_days,
            "threshold_source": plan.threshold_source, "benchmark_claim_id": plan.benchmark_claim_id,
            "excluded_sources": d["excluded_sources"], "change_our_mind": plan.change_our_mind,
            "verdict_mapping": ">= threshold: GO; < 25% of threshold: STOP; otherwise PIVOT_BACK; no verdict before the window closes; INSUFFICIENT_SAMPLE below min_visitors"}
    lock = gates.lock_rule(run_id, "experiment", rule)
    kv_set(run_id, "experiment_started_at", lock["locked_at"])
    decision_log.append(run_id, "gate", "lock_experiment_rule", approved_by="founder", sha256=lock["sha256"])
    write(run_id, 2, "step3", "experiment_rule_locked", json.dumps(lock, indent=1), "json")
    lc = landing_page.copy(run_id, brief, canvas, plan)
    keep(run_id, "landing_copy", lc)
    text = " ".join([lc.headline, lc.subheadline, *lc.bullets, *(f.a for f in lc.faq)])
    report = verify_public_copy(run_id, "landing_page", text)
    html = landing_page.render(run_id, lc)
    lp = data_dir() / "landing"
    lp.mkdir(exist_ok=True)
    (lp / f"{run_id}.html").write_text(html, encoding="utf-8")
    write(run_id, 2, "step4", "landing_page", html, "html", guard_check=True)
    write(run_id, 2, "step4", "landing_page_claims_check", report)
    outbox.submit(run_id, "serve_landing_page", title="Serve waitlist landing page locally", content=text,
                  target=f"/lp/{run_id}", target_provenance=Provenance.founder, requested_by="landing_page")
    recheck_experiment(run_id)


def experiment_status(run_id: str, now: Optional[str] = None) -> gates.GateResult:
    lock = gates.get_lock(run_id, "experiment")
    with conn() as c:
        visitors = c.execute("SELECT COUNT(*) n FROM visits WHERE run_id=? AND source NOT IN ('demo_audience','simulated')", (run_id,)).fetchone()["n"]
        signups = [dict(r) for r in c.execute("SELECT email, ts, source FROM signups WHERE run_id=?", (run_id,)).fetchall()]
    return gates.experiment_gate(lock["rule"] if lock else None, started_at=kv_get(run_id, "experiment_started_at"),
                                 now=now or now_iso(), visitors=visitors, signups=signups,
                                 excluded_sources=(lock["rule"]["excluded_sources"] if lock else ["demo_audience", "simulated"]))


def recheck_experiment(run_id: str) -> None:
    update(run_id, status="running", phase=2)
    result = experiment_status(run_id)
    lock = gates.get_lock(run_id, "experiment")
    pause_at_gate(run_id, "experiment", result, lock["rule"] if lock else {}, 2)
    finish(run_id)


def replay_fixture(name: str) -> dict[str, Any]:
    """MOCKED replay through the same gate code. Never touches a run's evidence."""
    fx = json.loads((EVALS_DIR / "fixtures" / "experiments" / f"{name}.json").read_text(encoding="utf-8"))
    res = gates.experiment_gate(fx["rule"], started_at=fx["started_at"], now=fx["now"], visitors=fx["visitors"],
                                signups=fx["signups"], excluded_sources=fx["rule"]["excluded_sources"])
    return {"label": "MOCKED", "fixture": name, "result": res.to_dict()}


def verify_public_copy(run_id: str, name: str, text: str) -> str:
    """Cross-model verification of every factual sentence in public-facing copy."""
    claims = ledger.all_claims(run_id)
    lines = [f"# Claim check: {name} (checked by {llm.model_name('claim_checker')})", "", "| sentence | label | ledger claim |", "|---|---|---|"]
    for s in quality.factual_sentences(text):
        c = quality.best_claim(s, claims)
        label = "ASSUMPTION"
        if c and c.source_url:
            try:
                from app.services import reader
                page = reader.fetch(c.source_url, caps()["page_chars"])
                label = claim_checker.check_against_ledger(run_id, s, c, page["text"])
            except Exception as e:
                label = f"ASSUMPTION (check failed: {type(e).__name__})"
        ledger.new(run_id, text=s, type="other", label=Label.SUPPORTED if label == "SUPPORTED" else Label.ASSUMPTION,
                   source_url=c.source_url if c and label == "SUPPORTED" else None, provenance=Provenance.agent,
                   artifact_id=name, writer_family=llm.family_of("copywriter"),
                   checked_by_family=llm.family_of("claim_checker"), checked_by_model=llm.model_name("claim_checker"))
        lines.append(f"| {s.replace('|', '/')} | {label} | {c.id if c else '-'} |")
    if len(lines) == 4:
        lines.append("| (no factual statements found) | - | - |")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- Phase 3 ----------------
def phase3(run_id: str) -> None:
    update(run_id, status="running", phase=3)
    events.emit(run_id, "phase", "Phase 3 - Build")
    brief, ideas, canvas = artifact(run_id, "brief", Brief), artifact(run_id, "ideas", IdeaMatrix), artifact(run_id, "canvas", LeanCanvas)
    prd = artifact(run_id, "prd", PRD) or planner.prd(run_id, brief, ideas, canvas)
    keep(run_id, "prd", prd)
    write(run_id, 3, "step1", "prd", "# PRD\n\n```json\n" + prd.model_dump_json(indent=1) + "\n```\n")
    spec = test_writer.run(run_id, prd)  # sees the PRD only, never the product
    spec_path = decision_log.run_dir(run_id) / "phase3_step2_test_spec.json"
    spec_path.write_text(spec.model_dump_json(indent=1), encoding="utf-8")
    max_attempts = gate_definitions()["tests_gate"]["max_attempts"]
    pack: Optional[GuidePack] = None
    failures: list[str] = []
    result = None
    for attempt in range(1, max_attempts + 1):
        events.check_kill()
        pack = builder.run(run_id, prd, failures or None, pack)
        out = decision_log.run_dir(run_id) / "product" / f"attempt{attempt}"
        builder.write(pack, out)
        report_path = out / "test_report.json"
        proc = subprocess.run([sys.executable, "-m", "app.product.test_runner", str(out), str(spec_path), str(report_path)],
                              capture_output=True, text=True, timeout=120, cwd=str(Path(__file__).resolve().parents[2]))
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"failures": [proc.stderr[-500:]]}
        failures = report.get("failures", [])
        decision_log.append(run_id, "test_runner", "run_product_tests", model=None, exit_code=proc.returncode,
                            attempt=attempt, failures=failures[:10])
        result = gates.tests_gate(proc.returncode, attempt, max_attempts)
        events.emit(run_id, "step", f"tests attempt {attempt}: exit {proc.returncode}")
        if proc.returncode == 0:
            break
        lessons.add(run_id, "tests", f"Product test failures: {'; '.join(failures[:3])}")
    assert pack is not None and result is not None
    keep(run_id, "guide_pack", pack)
    final_dir = decision_log.run_dir(run_id) / "product" / f"attempt{attempt}"
    write(run_id, 3, "step3", "product_guide", (final_dir / "guide.md").read_text(encoding="utf-8"), guard_check=True)
    write(run_id, 3, "step3", "product_guide", (final_dir / "guide.html").read_text(encoding="utf-8"), "html")
    write(run_id, 3, "step4", "test_report", "# Product tests (code runner, exit code decides)\n\n```json\n"
          + json.dumps({"attempts": attempt, "exit_code_zero": result.verdict == Verdict.GO, "failures": failures}, indent=1) + "\n```\n")
    docs = commercial.docs(run_id, pack)
    write(run_id, 3, "step5", "user_docs", docs.markdown, guard_check=True)
    pause_at_gate(run_id, "tests", result, {"rule": "test runner exit code == 0", "max_attempts": max_attempts,
                                            "spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest()}, 3)
    finish(run_id)


# ----------------------------------------------------------------- Phase 4 ----------------
def phase4(run_id: str) -> None:
    update(run_id, status="running", phase=4)
    events.emit(run_id, "phase", "Phase 4 - Commercial setup")
    brief, canvas, pack = artifact(run_id, "brief", Brief), artifact(run_id, "canvas", LeanCanvas), artifact(run_id, "guide_pack", GuidePack)
    claims = ledger.all_claims(run_id)
    sheet = commercial.pricing(run_id, brief, canvas, claims)
    keep(run_id, "pricing", sheet)
    write(run_id, 4, "step1", "pricing", "# Pricing (proposal; founder approves)\n\n| tier | price (USD) | includes |\n|---|---|---|\n"
          + "\n".join(f"| {t.name} | {t.price_usd:.2f} | {'; '.join(t.includes)} |" for t in sheet.tiers)
          + f"\n\nRationale: {sheet.rationale}\n\nCompetitor price claims: {', '.join(sheet.competitor_claim_ids) or 'none verified (ASSUMPTION)'}\n"
          + "\nNo payment code exists; checkout would run in the founder's own payment provider.\n", guard_check=True)
    pol = commercial.policies(run_id, brief, pack.title, sheet)
    keep(run_id, "policies", pol)
    for name, body in (("terms", pol.terms_md), ("privacy", pol.privacy_md), ("refund", pol.refund_md)):
        if not body.lstrip().upper().startswith("DRAFT"):
            body = "DRAFT - not legal advice - confirm with a lawyer.\n\n" + body
        write(run_id, 4, "step2", f"policy_{name}_DRAFT", body, guard_check=True)
    cl = compliance.checklist(run_id, brief, pack.title)
    srcs = {s["id"]: s for s in compliance.sources()}
    write(run_id, 4, "step3", "compliance_checklist", "# Compliance checklist\n\n" + compliance.DISCLAIMER + "\n\n| item | applies | source | note |\n|---|---|---|---|\n"
          + "\n".join(f"| {i.item} | {i.applies} | {srcs[i.source_id]['url'] if i.source_id in srcs else 'ASSUMPTION'} | {i.note} |" for i in cl.items) + "\n")
    issues = quality.consistency(canvas, sheet)
    write(run_id, 4, "step4", "consistency_check", "# Cross-phase consistency\n\n" + ("\n".join(f"- MISMATCH: {i}" for i in issues) or "- No mismatches found.") + "\n")
    _approval_gate(run_id, "commercial", 4, [f"Price tiers: {', '.join(f'{t.name} ${t.price_usd:.2f}' for t in sheet.tiers)}",
                                             "Policies are DRAFTS: not legal advice."], issues)
    finish(run_id)


# ----------------------------------------------------------------- Phase 5 ----------------
def phase5(run_id: str) -> None:
    update(run_id, status="running", phase=5)
    events.emit(run_id, "phase", "Phase 5 - Sell, deliver, get paid (MOCKED)")
    canvas, pack, sheet = artifact(run_id, "canvas", LeanCanvas), artifact(run_id, "guide_pack", GuidePack), artifact(run_id, "pricing", PricingSheet)
    page = commercial.store_page(run_id, pack, sheet, canvas)
    keep(run_id, "store_page", page)
    text = " ".join([page.title, page.tagline, page.description, *page.bullets, *(f.a for f in page.faq)])
    write(run_id, 5, "step1", "store_page", f"# {page.title}\n\n_{page.tagline}_\n\n{page.description}\n\n"
          + "\n".join(f"- {b}" for b in page.bullets) + "\n\n" + "\n".join(f"**{t.name}**: ${t.price_usd:.2f}" for t in sheet.tiers)
          + "\n\n" + "\n".join(f"**{f.q}** {f.a}" for f in page.faq) + "\n", guard_check=True)
    write(run_id, 5, "step1", "store_page_claims_check", verify_public_copy(run_id, "store_page", text))
    issues = quality.consistency(canvas, sheet, page, artifact(run_id, "prd", PRD))
    outbox.submit(run_id, "publish_store_page", title=f"Publish store page: {page.title}", content=text,
                  target="founder's own store (MOCKED connector)", target_provenance=Provenance.founder, requested_by="store_page")
    channels = [i.text for i in canvas.channels][:3] or ["founder newsletter"]
    posts = commercial.launch_posts(run_id, page, channels)
    keep(run_id, "launch_posts", posts)
    for p in posts.posts:
        outbox.submit(run_id, "post", title=f"Launch post ({p.channel})", content=p.text,
                      target=p.channel, target_provenance=Provenance.agent, requested_by="launch_post")
    write(run_id, 5, "step2", "launch_posts", "# Launch posts (queued in the Outbox; founder approves each; connectors MOCKED)\n\n"
          + "\n\n".join(f"## {p.channel}\n\n{p.text}" for p in posts.posts) + "\n", guard_check=True)
    # Sale-to-cash test: MOCKED order -> MOCKED delivery (idempotent) -> MOCKED refund request -> reconcile.
    tier = sheet.tiers[0]
    order = payments.simulate_order_received(run_id, tier.name, tier.price_usd)
    delivery.deliver(run_id, order["order_id"])
    delivery.deliver(run_id, order["order_id"])  # duplicate event: must not deliver twice
    refunds.request_refund(run_id, order["order_id"], "MOCKED test refund request")
    rec = refunds.reconcile(run_id)
    log = (decision_log.run_dir(run_id) / "payment_test_log.md").read_text(encoding="utf-8")
    write(run_id, 5, "step3", "sale_to_cash_test", log + f"\nReconciliation: {json.dumps(rec)}\n")
    _approval_gate(run_id, "launch", 5, ["Store page and posts wait in the Outbox for one-by-one approval (MOCKED connectors)."], issues)
    finish(run_id)


# ----------------------------------------------------------------- Phase 6 ----------------
def phase6(run_id: str) -> None:
    update(run_id, status="running", phase=6)
    events.emit(run_id, "phase", "Phase 6 - Operate and learn")
    pol = artifact(run_id, "policies", PolicyDrafts)
    fx = json.loads((EVALS_DIR / "fixtures" / "metrics_mock.json").read_text(encoding="utf-8"))
    sup = commercial.support(run_id, fx["tickets"], pol)
    write(run_id, 6, "step1", "support_drafts_SHADOW", "# Support replies - SHADOW MODE (MOCKED tickets)\n\n"
          "These are what the system WOULD send. Nothing is sent until the founder signs off; then each goes through the Outbox.\n\n"
          + "\n\n".join(f"## Ticket {r.ticket_id}\n\n{r.draft}" for r in sup.replies) + "\n", guard_check=True)
    kv_set(run_id, "shadow_support", [r.model_dump() for r in sup.replies])
    m = commercial.metrics(run_id, fx["metrics"])
    write(run_id, 6, "step2", "metrics_MOCKED", "# Metrics (MOCKED data - not evidence)\n\n```json\n" + json.dumps(fx["metrics"], indent=1)
          + "\n```\n\n## Reading\n\n" + "\n".join(f"- {o}" for o in m.observations) + "\n\n## Risks\n\n" + "\n".join(f"- {r}" for r in m.risks) + "\n")
    exp = experiment_status(run_id)
    st = load(run_id)
    desk = st["gates"].get("desk_evidence", {}).get("result", {}).get("verdict")
    overrides = [g for g, r in st["gates"].items() if r.get("decision") and r["decision"]["override"]]
    if exp.state == "VERDICT" and exp.verdict == Verdict.GO:
        rec = "PERSEVERE"
    elif exp.state == "VERDICT" and exp.verdict == Verdict.STOP:
        rec = "STOP"
    elif exp.state == "VERDICT":
        rec = "PIVOT"
    else:
        rec = "WAIT_FOR_EVIDENCE"
    facts = {"desk_gate": desk, "experiment_state": exp.state, "experiment_reasons": exp.reasons,
             "founder_overrides": overrides, "metrics": "MOCKED (not evidence)"}
    memo = commercial.memo(run_id, facts, rec)
    body = memo.body if memo.body.strip().startswith(f"Recommendation: {rec}") else f"Recommendation: {rec}.\n\n" + memo.body
    write(run_id, 6, "step3", "persevere_or_pivot_memo", body, guard_check=True)
    update(run_id, status="done", phase=6)
    finish(run_id)
    events.emit(run_id, "done", f"Run complete. Memo recommendation: {rec}")


PHASE_FN: dict[int, Callable[[str], None]] = {1: phase1, 2: phase2, 3: phase3, 4: phase4, 5: phase5, 6: phase6}


# ----------------------------------------------------------------- dashboards -------------
def founder_control(run_id: str) -> dict[str, Any]:
    log = decision_log.read(run_id)
    gate_decisions = [e for e in log if e["action"].startswith("gate_decision_")]
    raised = [e for e in log if e.get("initiated_by")]
    return {
        "gate_decisions": len(gate_decisions),
        "share_by_founder": round(sum(1 for e in gate_decisions if e.get("chosen_by") == "founder") / len(gate_decisions), 3) if gate_decisions else None,
        "overrides": [{"action": e["action"], "reason": e.get("override_reason")} for e in gate_decisions if e.get("override")],
        "raised_by_agent": sum(1 for e in raised if e["initiated_by"] == "agent"),
        "raised_by_founder": sum(1 for e in raised if e["initiated_by"] == "founder"),
        "approved_outward_actions": sum(1 for e in log if e["agent"] == "outbox" and e.get("approved_by") == "founder"),
    }


def publish(run_id: str) -> list[str]:
    """Copy a finished run to the flat outputs/ layout and the root decision_log.json (the committed demo run)."""
    from app.config import outputs_dir
    rd = decision_log.run_dir(run_id)
    copied = []
    for p in sorted(rd.glob("phase*")):
        decision_log.copy_file(p, outputs_dir() / p.name)
        copied.append(p.name)
    for extra in ("payment_test_log.md", "cost.json"):
        if (rd / extra).exists():
            decision_log.copy_file(rd / extra, outputs_dir() / extra)
            copied.append(extra)
    decision_log.publish_to_root(run_id)
    (outputs_dir() / "DEMO_RUN.txt").write_text(f"Files in outputs/ (flat) come from run {run_id}. All runs: outputs/runs/.\n", encoding="utf-8")
    return copied

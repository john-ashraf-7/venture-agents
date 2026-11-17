"""Gates. Verdicts are computed HERE, in plain code, against rules locked before the evidence was
gathered. LLMs only explain a verdict; they never compute or change it.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.models import Verdict, now_iso
from app.services.storage import conn


# ----------------------------------------------------------------- rule locking -----------
class RuleLockError(RuntimeError):
    pass


def _hash(rule: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()


def lock_rule(run_id: str, name: str, rule: dict[str, Any]) -> dict[str, Any]:
    """Store a gate rule with hash + timestamp. A locked rule can never be changed."""
    existing = get_lock(run_id, name)
    if existing:
        if existing["sha256"] != _hash(rule):
            raise RuleLockError(f"Gate rule {name!r} is locked since {existing['locked_at']}; it is read-only.")
        return existing
    rec = {"id": f"{run_id}:{name}", "run_id": run_id, "name": name, "rule": rule, "sha256": _hash(rule), "locked_at": now_iso()}
    with conn() as c:
        c.execute("INSERT INTO locks (id, run_id, name, body, sha256, locked_at) VALUES (?,?,?,?,?,?)",
                  (rec["id"], run_id, name, json.dumps(rule, sort_keys=True), rec["sha256"], rec["locked_at"]))
    return rec


def get_lock(run_id: str, name: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT * FROM locks WHERE id=?", (f"{run_id}:{name}",)).fetchone()
    if not row:
        return None
    rule = json.loads(row["body"])
    if _hash(rule) != row["sha256"]:
        raise RuleLockError(f"Locked rule {name!r} fails its hash check (tampered).")
    return {"id": row["id"], "run_id": run_id, "name": name, "rule": rule, "sha256": row["sha256"], "locked_at": row["locked_at"]}


# ----------------------------------------------------------------- results ----------------
@dataclass
class Check:
    name: str
    value: Any
    threshold: Any
    passed: Optional[bool]
    note: str = ""


@dataclass
class GateResult:
    gate: str
    verdict: Verdict
    checks: list[Check] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    state: Optional[str] = None
    computed_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        return d


# ----------------------------------------------------------------- desk gate --------------
@dataclass
class DeskEvidence:
    demand_signals: int
    paying_competitors: int
    direct_competitors: int
    blocking_flags: int
    cost_high_usd: Optional[float]
    budget_usd: Optional[float]
    hours_high: Optional[float]
    hours_available: Optional[float]
    missing_skills: list[str] = field(default_factory=list)


def founder_fit(ev: DeskEvidence) -> tuple[Optional[bool], str]:
    problems, unknown = [], []
    if ev.cost_high_usd is None or ev.budget_usd is None:
        unknown.append("budget or cost estimate missing")
    elif ev.cost_high_usd > ev.budget_usd:
        problems.append(f"high-end cost ${ev.cost_high_usd:,.0f} > budget ${ev.budget_usd:,.0f}")
    if ev.hours_high is None or ev.hours_available is None:
        unknown.append("time available or hours estimate missing")
    elif ev.hours_high > ev.hours_available:
        problems.append(f"high-end effort {ev.hours_high:.0f} h > {ev.hours_available:.0f} h available")
    if ev.missing_skills:
        problems.append("missing skills: " + ", ".join(ev.missing_skills))
    if problems:
        return False, "; ".join(problems)
    if unknown:
        return None, "; ".join(unknown)
    return True, "plan fits budget, time and skills (high end of ASSUMPTION ranges)"


def desk_gate(rule: dict[str, Any], ev: DeskEvidence) -> GateResult:
    dmin = int(rule["demand_signals_min"])
    pmin = int(rule["paying_competitors_min"])
    dmax = int(rule["direct_competitors_max"])
    fmax = int(rule["blocking_compliance_flags_max"])
    fit_ok, fit_note = founder_fit(ev)
    checks = [
        Check("demand_signals", ev.demand_signals, f">= {dmin}", ev.demand_signals >= dmin),
        Check("paying_competitors", ev.paying_competitors, f">= {pmin}", ev.paying_competitors >= pmin),
        Check("direct_competitors", ev.direct_competitors, f"<= {dmax}", ev.direct_competitors <= dmax),
        Check("blocking_compliance_flags", ev.blocking_flags, f"<= {fmax}", ev.blocking_flags <= fmax),
        Check("founder_fit", fit_note, "high end within budget/time; skills covered", fit_ok),
    ]
    reasons: list[str] = []
    if ev.blocking_flags > fmax:
        verdict = Verdict.STOP
        reasons.append("A blocking compliance flag was raised.")
    elif ev.demand_signals < math.ceil(dmin / 2):
        verdict = Verdict.STOP
        reasons.append(f"Only {ev.demand_signals} verified demand signal(s); the locked minimum is {dmin}.")
    elif ev.demand_signals < dmin:
        verdict = Verdict.PARK
        reasons.append(f"{ev.demand_signals} verified demand signals, below the locked minimum of {dmin}.")
    elif ev.paying_competitors < pmin:
        verdict = Verdict.PARK
        reasons.append("No competitor with a verified price: willingness to pay is unproven.")
    elif ev.direct_competitors > dmax:
        verdict = Verdict.PIVOT_BACK
        reasons.append(f"{ev.direct_competitors} direct competitors (max {dmax}): niche down.")
    elif fit_ok is not True:
        verdict = Verdict.PARK
        reasons.append("Founder fit: " + fit_note + (" (ask the founder before assuming)" if fit_ok is None else ""))
    else:
        verdict = Verdict.GO
        reasons.append("Every locked threshold is met.")
    return GateResult("desk_evidence", verdict, checks, reasons)


# ----------------------------------------------------------------- experiment gate --------
def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def count_signups(signups: list[dict[str, Any]], excluded_sources: list[str]) -> int:
    return sum(1 for s in signups if s.get("source") not in excluded_sources)


def experiment_gate(rule: Optional[dict[str, Any]], *, started_at: Optional[str], now: str,
                    visitors: int, signups: list[dict[str, Any]], excluded_sources: list[str]) -> GateResult:
    """States: NOT_STARTED -> IN_PROGRESS -> INSUFFICIENT_SAMPLE | VERDICT. No verdict before the window closes."""
    counted = count_signups(signups, excluded_sources)
    excluded = len(signups) - counted
    if not rule or not started_at:
        return GateResult("experiment", Verdict.PARK, [], ["Experiment not started."], state="NOT_STARTED")
    window = int(rule["window_days"])
    threshold = int(rule["signups_threshold"])
    min_visitors = int(rule["min_visitors"])
    elapsed_days = (_parse(now) - _parse(started_at)).total_seconds() / 86400
    checks = [Check("signups_counted", counted, f">= {threshold}", None, f"{excluded} excluded (demo audience / simulated)"),
              Check("visitors", visitors, f">= {min_visitors}", visitors >= min_visitors)]
    if elapsed_days < window:
        day = min(window, int(elapsed_days) + 1)
        return GateResult("experiment", Verdict.REPEAT, checks,
                          [f"{counted} sign-ups, day {day} of {window}, too early to judge."], state="IN_PROGRESS")
    if visitors < min_visitors:
        return GateResult("experiment", Verdict.REPEAT, checks,
                          [f"Only {visitors} visitors (min {min_visitors}): sample too small to judge; extend or re-run."],
                          state="INSUFFICIENT_SAMPLE")
    checks[0].passed = counted >= threshold
    ratio = counted / threshold
    if counted >= threshold:
        verdict, why = Verdict.GO, f"{counted} sign-ups met the locked threshold of {threshold}."
    elif ratio < 0.25:
        verdict, why = Verdict.STOP, f"{counted} sign-ups is {ratio:.0%} of the locked threshold of {threshold}."
    else:
        verdict, why = Verdict.PIVOT_BACK, f"{counted} sign-ups is {ratio:.0%} of the locked threshold of {threshold}; revisit the offer or segment."
    return GateResult("experiment", verdict, checks, [why], state="VERDICT")


# ----------------------------------------------------------------- tests gate -------------
def tests_gate(exit_code: int, attempt: int, max_attempts: int = 3) -> GateResult:
    """Reads the test runner's exit code. No LLM can declare tests passed."""
    passed = exit_code == 0
    checks = [Check("test_runner_exit_code", exit_code, "== 0", passed), Check("attempt", attempt, f"<= {max_attempts}", attempt <= max_attempts)]
    if passed:
        return GateResult("tests", Verdict.GO, checks, ["All product tests passed (exit code 0)."])
    if attempt < max_attempts:
        return GateResult("tests", Verdict.REPEAT, checks, [f"Tests failed on attempt {attempt}; revising."])
    return GateResult("tests", Verdict.PARK, checks, [f"Tests still failing after {max_attempts} attempts: founder decides REPEAT or PARK."])


# ----------------------------------------------------------------- explanation helpers ----
SENTENCE = re.compile(r"^(.+?[.!?])(\s|$)", re.S)


def recommendation_sentence(verdict: Verdict) -> str:
    return {
        Verdict.GO: "Recommendation: GO.",
        Verdict.REPEAT: "Recommendation: REPEAT.",
        Verdict.PIVOT_BACK: "Recommendation: PIVOT_BACK.",
        Verdict.PARK: "Recommendation: PARK.",
        Verdict.STOP: "Recommendation: STOP.",
    }[verdict]


def enforce_first_sentence(text: str, verdict: Verdict) -> str:
    """The first sentence of any gate explanation must state the code-computed recommendation."""
    text = (text or "").strip()
    m = SENTENCE.match(text)
    first = m.group(1) if m else text
    if verdicts_in(first) == {verdict}:
        return text
    return recommendation_sentence(verdict) + " " + text


def verdicts_in(sentence: str) -> set[Verdict]:
    s = sentence.upper().replace("PIVOT BACK", "PIVOT_BACK").replace("PIVOT-BACK", "PIVOT_BACK")
    return {v for v in Verdict if re.search(rf"(?<![A-Z_]){v.value}(?![A-Z_])", s)}


def first_sentence(text: str) -> str:
    m = SENTENCE.match((text or "").strip())
    return m.group(1) if m else (text or "").strip()


def options_for(result: GateResult) -> list[dict[str, Any]]:
    """2-3 options with evidence and risk. The option with the weakest evidence is flagged."""
    v = result.verdict
    ev = "; ".join(result.reasons)
    table = {
        Verdict.GO: [("GO", "Proceed / approve", ev, "Desk evidence and drafts are not proof of real demand."),
                     ("REPEAT", "Revise this step", "Not needed by the locked rule", "Time."),
                     ("PARK", "Pause", "Not needed by the locked rule", "Delay.")],
        Verdict.STOP: [("STOP", "Stop this idea and write the STOP memo", ev, "May drop an idea that a different segment would want."),
                       ("PIVOT_BACK", "Go back to Discover with a narrower niche", "Weak demand suggests re-scoping", "Costs another research cycle."),
                       ("GO", "Override and continue anyway (typed reason required)", "Contradicts the locked threshold", "Builds on unproven demand.")],
        Verdict.PARK: [("PARK", "Pause; collect the missing evidence first", ev, "Momentum loss."),
                       ("PIVOT_BACK", "Re-scope the idea", "Partial evidence", "Another research cycle."),
                       ("GO", "Override and continue anyway (typed reason required)", "Below the locked threshold", "Builds on unproven demand.")],
        Verdict.PIVOT_BACK: [("PIVOT_BACK", "Niche down and re-run Discover", ev, "Smaller market."),
                             ("PARK", "Pause", "Not addressed", "Delay."),
                             ("GO", "Override and continue in a crowded market (typed reason required)", "Contradicts the locked rule", "Crowded market.")],
        Verdict.REPEAT: [("REPEAT", "Repeat / check again later", ev, "Time."),
                         ("PARK", "Pause", "Not addressed", "Delay."),
                         ("GO", "Override and continue without a verdict (typed reason required)", "No verdict yet", "Builds on unmeasured demand.")],
    }[v]
    out = [{"choice": c, "label": label, "evidence": e, "risk": r, "recommended": i == 0, "weakest_evidence": False}
           for i, (c, label, e, r) in enumerate(table)]
    if len(out) > 1:
        weakest = next((o for o in out if o["choice"] == "GO" and not o["recommended"]), out[-1])
        weakest["weakest_evidence"] = True
    return out

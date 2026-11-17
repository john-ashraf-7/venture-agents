"""Gate logic: desk-gate mapping, experiment states, MOCKED fixtures, rule locking, tests gate."""
import pytest

from app import gates
from app.models import Verdict
from app.orchestrator import orchestrator as orch

RULE = {"demand_signals_min": 3, "paying_competitors_min": 1, "direct_competitors_max": 4, "blocking_compliance_flags_max": 0}


def ev(**kw):
    base = dict(demand_signals=4, paying_competitors=2, direct_competitors=2, blocking_flags=0, cost_high_usd=200,
                budget_usd=300, hours_high=40, hours_available=48, missing_skills=[])
    base.update(kw)
    return gates.DeskEvidence(**base)


@pytest.mark.parametrize("kw,verdict", [
    ({}, Verdict.GO),
    ({"blocking_flags": 1}, Verdict.STOP),
    ({"demand_signals": 0}, Verdict.STOP),
    ({"demand_signals": 1}, Verdict.STOP),
    ({"demand_signals": 2}, Verdict.PARK),
    ({"paying_competitors": 0}, Verdict.PARK),
    ({"direct_competitors": 9}, Verdict.PIVOT_BACK),
    ({"cost_high_usd": 900}, Verdict.PARK),
    ({"hours_high": 200}, Verdict.PARK),
    ({"budget_usd": None}, Verdict.PARK),
])
def test_desk_gate_mapping(kw, verdict):
    assert gates.desk_gate(RULE, ev(**kw)).verdict == verdict


def test_founder_fit_uses_high_end_of_range():
    ok, _ = gates.founder_fit(ev(cost_high_usd=301, budget_usd=300))
    assert ok is False


EXP = {"signups_threshold": 100, "min_visitors": 500, "window_days": 14}
EXCL = ["demo_audience", "simulated"]


def su(n, src="direct"):
    return [{"email": f"a{i}@x.io", "ts": "t", "source": src} for i in range(n)]


def test_experiment_in_progress_never_gives_verdict():
    r = gates.experiment_gate(EXP, started_at="2026-11-01T00:00:00Z", now="2026-11-05T00:00:00Z", visitors=900,
                              signups=su(500), excluded_sources=EXCL)
    assert r.state == "IN_PROGRESS" and "too early to judge" in r.reasons[0] and "day 5 of 14" in r.reasons[0]


def test_experiment_insufficient_sample():
    r = gates.experiment_gate(EXP, started_at="2026-11-01T00:00:00Z", now="2026-11-20T00:00:00Z", visitors=100,
                              signups=su(150), excluded_sources=EXCL)
    assert r.state == "INSUFFICIENT_SAMPLE"


def test_experiment_not_started():
    assert gates.experiment_gate(None, started_at=None, now="2026-11-20T00:00:00Z", visitors=0, signups=[], excluded_sources=EXCL).state == "NOT_STARTED"


def test_simulated_fixture_12_of_100_stops():
    out = orch.replay_fixture("signups_12_of_100")
    assert out["label"] == "MOCKED"
    assert out["result"]["state"] == "VERDICT" and out["result"]["verdict"] == "STOP"


def test_simulated_fixture_130_of_100_goes():
    assert orch.replay_fixture("signups_130_of_100")["result"]["verdict"] == "GO"


def test_demo_audience_signups_never_count():
    r = gates.experiment_gate(EXP, started_at="2026-11-01T00:00:00Z", now="2026-11-20T00:00:00Z", visitors=900,
                              signups=su(20) + su(200, "demo_audience") + su(50, "simulated"), excluded_sources=EXCL)
    assert r.checks[0].value == 20 and r.verdict == Verdict.STOP


def test_locked_rule_is_read_only():
    gates.lock_rule("r1", "desk", RULE)
    assert gates.lock_rule("r1", "desk", RULE)["sha256"]  # same content: fine
    with pytest.raises(gates.RuleLockError):
        gates.lock_rule("r1", "desk", {**RULE, "demand_signals_min": 1})


def test_tests_gate_reads_exit_code_only():
    assert gates.tests_gate(0, 1).verdict == Verdict.GO
    assert gates.tests_gate(1, 1).verdict == Verdict.REPEAT
    assert gates.tests_gate(1, 3).verdict == Verdict.PARK


def test_weakest_evidence_option_flagged():
    opts = gates.options_for(gates.desk_gate(RULE, ev(demand_signals=0)))
    assert 2 <= len(opts) <= 3
    assert any(o["weakest_evidence"] for o in opts) and opts[0]["recommended"] and opts[0]["choice"] == "STOP"

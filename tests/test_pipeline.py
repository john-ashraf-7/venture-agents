"""End-to-end smoke test of all six phases (STUBBED LLM, fixture search), plus founder-approval rules."""
import json
import re

import pytest

from app import approval
from app.models import FounderInput
from app.orchestrator import orchestrator as orch
from app.services import decision_log, outbox
from tests.conftest import FOUNDER

NAME = re.compile(r"^phase[1-6]_(step\d+|gate)_[\w-]+\.(md|json|html|csv|txt)$")


def run_phase1():
    st = orch.start(FounderInput(**FOUNDER), background=False)
    assert st["status"] == "awaiting_founder", st.get("error")
    return st["id"]


def test_phase1_reaches_code_computed_desk_gate():
    rid = run_phase1()
    st = orch.load(rid)
    rec = st["gates"]["desk_evidence"]
    assert rec["result"]["verdict"] in {"GO", "PARK", "STOP", "PIVOT_BACK"}
    assert rec["explanation"].startswith("Recommendation: " + rec["result"]["verdict"])
    files = [p.name for p in decision_log.run_dir(rid).glob("phase*")]
    assert "phase1_gate_desk_evidence.md" in files and "phase1_step2_gate_rule_locked.json" in files
    assert all(NAME.match(f) for f in files), files
    # the rule was locked before the first search
    log = decision_log.read(rid)
    actions = [e["action"] for e in log]
    assert actions.index("lock_desk_gate_rule") < actions.index("web_search")
    for e in log:
        for k in decision_log.REQUIRED:
            assert k in e


def test_unsupported_claim_is_rewritten_not_deleted():
    rid = run_phase1()
    from app.services import ledger
    claims = ledger.all_claims(rid)
    ten_k = [c for c in claims if "$10,000" in c.text]
    assert ten_k and ten_k[0].label.value == "ASSUMPTION" and "Rewritten" in (ten_k[0].note or "")


def test_override_of_stop_requires_reason():
    with pytest.raises(approval.ApprovalError):
        approval.decide("rx", "desk_evidence", approval.Verdict.STOP, "GO", "")
    d = approval.decide("rx", "desk_evidence", approval.Verdict.STOP, "GO", "I have 40 pre-orders from my newsletter")
    assert d["override"] is True


def test_full_run_through_six_phases_with_founder_approvals():
    rid = run_phase1()
    rec = orch.load(rid)["gates"]["desk_evidence"]["result"]["verdict"]
    reason = "" if rec == "GO" else "Testing the full pipeline end to end for the demo"
    orch.decide(rid, "desk_evidence", "GO", reason, background=False)
    assert orch.load(rid)["awaiting"]["gate"] == "experiment_plan"
    orch.decide(rid, "experiment_plan", "GO", background=False)
    st = orch.load(rid)
    assert st["gates"]["experiment"]["result"]["state"] == "IN_PROGRESS"
    # landing page is queued in the Outbox and NOT served before approval
    items = outbox.items(rid)
    lp = [i for i in items if i["kind"] == "serve_landing_page"][0]
    assert lp["status"] == "pending_approval"
    with pytest.raises(approval.ApprovalError):
        orch.decide(rid, "experiment", "GO", "", background=False)  # no verdict yet: override needs a reason
    orch.decide(rid, "experiment", "GO", "Proceeding to build for the demo; experiment still running", background=False)
    assert orch.load(rid)["gates"]["tests"]["result"]["verdict"] == "GO"
    orch.decide(rid, "tests", "GO", background=False)
    orch.decide(rid, "commercial", "GO", background=False)
    st = orch.load(rid)
    assert st["awaiting"]["gate"] == "launch"
    pending = [i for i in outbox.items(rid) if i["status"] == "pending_approval"]
    assert {i["kind"] for i in pending} >= {"publish_store_page", "post"}
    orch.decide(rid, "launch", "GO", background=False)
    st = orch.load(rid)
    assert st["status"] == "done"
    files = sorted(p.name for p in decision_log.run_dir(rid).glob("phase*"))
    assert any(f.startswith("phase6_step3_persevere_or_pivot_memo") for f in files)
    memo = (decision_log.run_dir(rid) / "phase6_step3_persevere_or_pivot_memo.md").read_text()
    assert memo.startswith("Recommendation: WAIT_FOR_EVIDENCE")
    log = (decision_log.run_dir(rid) / "payment_test_log.md").read_text()
    assert "idempotent" in log and "no money moved" in log
    # still nothing went out: every outward item waits for the founder
    assert not [i for i in outbox.items(rid) if i["tier"] == 1 and i["status"] == "done"]
    copied = orch.publish(rid)
    assert "payment_test_log.md" in copied
    from app.config import root_decision_log
    data = json.loads(root_decision_log().read_text(encoding="utf-8"))
    assert data and all(k in data[0] for k in decision_log.REQUIRED)


def test_excluded_product_blocked_at_intake():
    st = orch.start(FounderInput(idea="A paid Telegram channel with crypto trading signals", budget="$100"), background=False)
    assert st["status"] == "blocked" and "Excluded" in st["error"]


def test_kill_switch_stops_and_cancels():
    rid = run_phase1()
    outbox.submit(rid, "post", title="t", content="hello", target="newsletter")
    out = orch.kill()
    assert out["outbox_cancelled"] >= 1
    assert orch.load(rid)["status"] == "killed"
    assert all(i["status"] != "pending_approval" for i in outbox.items(rid))
    orch.unkill()


def test_demand_signals_count_only_from_forum_pages():
    rid = run_phase1()
    from app.services import ledger
    counted = orch.load(rid)["gates"]["desk_evidence"]["result"]["checks"][0]
    expected = {(c.source_url, c.type) for c in ledger.all_claims(rid) if ledger.counts_for_gate(c)
                and (c.type in ("paying_competitor", "trend") or (c.type == "demand_signal" and "/forum/" in c.source_url))}
    assert counted["name"] == "demand_signals" and counted["value"] == len(expected)


def test_cost_survives_a_new_process():
    rid = run_phase1()
    from app.services import cost
    before = cost.summary(rid)["llm_calls"]
    cost._RUNS.clear()  # what a later CLI process (founder decision) sees
    assert before > 0 and cost.summary(rid)["llm_calls"] == before


def test_partial_and_snippet_claims_never_count_at_the_gate():
    from app.agents import market_researcher
    from app.models import Claim, Label
    from app.services import ledger
    base = dict(id="C1", run_id="r", text="t", type="demand_signal", source_url="https://reddit.com/r/a",
                source_quote="q", writer_family="gpt-oss", checked_by_family="qwen")
    assert ledger.counts_for_gate(Claim(**base, label=Label.SUPPORTED))
    assert not ledger.counts_for_gate(Claim(**base, label=Label.PARTIAL))
    page = market_researcher.snippet_page("https://example.org/p", "Example title\nPro plan $12/month for teams", "pricing")
    assert market_researcher.is_snippet(page) and page["extract"]["problem_statements"] == []

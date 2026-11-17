"""Every LLM request and its raw reply is traced to data/llm_traces/<sha256>.json."""
import json

from app import llm
from app.config import data_dir
from app.models import PolicyDecision
from app.services import cost


def test_one_call_writes_one_trace_and_hash_in_cost_row():
    d = data_dir() / "llm_traces"
    before = set(d.glob("*.json")) if d.exists() else set()
    llm.call("policy_guard", [{"role": "user", "content": "Text:\nWrite a FAQ about file formats"}], PolicyDecision,
             run_id="trace_test", use_cache=False)
    new = set(d.glob("*.json")) - before
    assert len(new) == 1
    path = new.pop()
    row = cost.last_call("trace_test")
    assert row["trace"] == path.stem and len(row["trace"]) == 64
    t = json.loads(path.read_text(encoding="utf-8"))
    assert t["request"]["role"] == "policy_guard" and t["request"]["schema"] == "PolicyDecision"
    assert t["request"]["run_id"] == "trace_test" and t["request"]["messages"]
    assert json.loads(t["reply"])["decision"] == "ALLOW"
    assert not any(s in json.dumps(t).lower() for s in ("api_key", "authorization", "bearer "))

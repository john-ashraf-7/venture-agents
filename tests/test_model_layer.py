"""Model layer: role resolution, overrides, retries with validation feedback, escalation, cache, config checks."""
import json

import pytest

from app import llm
from app.models import CheckResult


def test_roles_resolve_and_env_override(monkeypatch):
    assert llm.resolve("claim_checker").model.family == "qwen"
    monkeypatch.setenv("ROLE_CLAIM_CHECKER", "gpt-oss-20b")
    assert llm.resolve("claim_checker").model.name == "gpt-oss:20b"


def test_default_config_has_no_family_warning():
    assert not [w for w in llm.config_warnings() if "same model family" in w]


def test_same_family_checker_warns(monkeypatch):
    monkeypatch.setenv("ROLE_CLAIM_CHECKER", "gpt-oss-20b")
    assert any("claim_checker" in w for w in llm.config_warnings())


def test_retry_feeds_validation_error_then_raises():
    calls = []

    def bad(model, messages, schema, t):
        calls.append(messages)
        return json.dumps({"label": "MAYBE", "reason": "x"}), 10, 5
    llm.set_backend(bad)
    with pytest.raises(llm.LLMError):
        llm.call("claim_checker", [{"role": "user", "content": "q-retry"}], CheckResult, use_cache=False)
    assert len(calls) == 3
    assert "failed validation" in calls[-1][-1]["content"]


def test_escalation_used_in_quality_profile(monkeypatch):
    monkeypatch.setenv("PROFILE", "quality")
    seen = []

    def by_model(model, messages, schema, t):
        seen.append(model.name)
        if model.name == "qwen3:8b":
            return "not json", 1, 1
        return json.dumps({"label": "SUPPORTED", "reason": "ok"}), 1, 1
    llm.set_backend(by_model)
    out = llm.call("claim_checker", [{"role": "user", "content": "q-esc"}], CheckResult, use_cache=False)
    assert out.label == "SUPPORTED" and seen[-1] == "gpt-oss:20b"


def test_cache_hit():
    n = []

    def once(model, messages, schema, t):
        n.append(1)
        return json.dumps({"label": "PARTIAL", "reason": "r"}), 1, 1
    llm.set_backend(once)
    llm.call("claim_checker", [{"role": "user", "content": "cache-me"}], CheckResult)
    llm.call("claim_checker", [{"role": "user", "content": "cache-me"}], CheckResult)
    assert len(n) == 1

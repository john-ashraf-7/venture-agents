"""local_transformers roles: MiniCheck claim checker (bands, sentence split, top-3 chunks) and the reranker.
The model scorers are STUBBED here; test_minicheck_real runs only where torch + the weights are present."""
import importlib.util
import os

import pytest

from app import llm
from app.agents import claim_checker
from app.llm import local_transformers as lt
from app.services import rerank


@pytest.fixture
def minicheck(monkeypatch):
    monkeypatch.setenv("ROLE_CLAIM_CHECKER", "minicheck-flan-t5")
    seen = []

    def fake(spec, pairs, batch=8):
        seen.extend(pairs)
        # supported iff the claim's key word is in the chunk
        return [0.97 if c.split()[-1].strip(".").lower() in d.lower() else 0.05 for d, c in pairs]
    monkeypatch.setattr(lt, "minicheck_scores", fake)
    return seen


def test_minicheck_role_resolves_with_own_family(minicheck):
    spec = llm.resolve("claim_checker")
    assert spec.model.provider_kind == "local_transformers" and spec.model.family == "flan-t5"
    assert not [w for w in llm.config_warnings() if "claim_checker" in w]


def test_bands_and_combine():
    assert claim_checker.band(0.95, 0.9, 0.5) == "SUPPORTED"
    assert claim_checker.band(0.6, 0.9, 0.5) == "PARTIAL"
    assert claim_checker.band(0.1, 0.9, 0.5) == "UNSUPPORTED"
    assert claim_checker.combine(["SUPPORTED", "SUPPORTED"]) == "SUPPORTED"
    assert claim_checker.combine(["SUPPORTED", "UNSUPPORTED"]) == "PARTIAL"
    assert claim_checker.combine(["UNSUPPORTED", "UNSUPPORTED"]) == "UNSUPPORTED"


def test_multi_sentence_claim_partial_when_one_part_fails(minicheck):
    src = "Freelancers say invoices are paid late. " * 5
    assert claim_checker.label_claim("Invoices are paid late.", "u", src).label == "SUPPORTED"
    assert claim_checker.label_claim("Invoices are paid late. Clients pay in bitcoin.", "u", src).label == "PARTIAL"
    assert claim_checker.label_claim("Clients pay in bitcoin.", "u", src).label == "UNSUPPORTED"


def test_only_top3_chunks_checked_and_max_taken(minicheck):
    filler = " ".join(f"word{i}" for i in range(3000))
    src = filler + " the reminder template costs twenty dollars " + filler
    res = claim_checker.label_claim("The reminder template costs twenty dollars.", "u", src)
    assert res.label == "SUPPORTED"
    assert len(minicheck) == 3  # one sentence x top-3 chunks, not every chunk of the page


def test_split_sentences():
    assert lt.split_sentences("A is 5. B is 6! c.d is fine") == ["A is 5.", "B is 6! c.d is fine"]


def test_rerank_sorts_and_keeps_fields():
    rerank.set_scorer(lambda q, ps: [0.9 if "pricing" in p.lower() else 0.1 for p in ps])
    try:
        res = [{"url": "https://a.test/blog", "title": "Blog", "snippet": "news", "engines": ["bing"]},
               {"url": "https://b.test/pricing", "title": "Pricing", "snippet": "plans", "engines": ["ddg"]}]
        out = rerank.rerank(rerank.purpose_text("pricing", competitor="Notion"), res)
    finally:
        rerank.set_scorer(None)
    assert [r["url"] for r in out] == ["https://b.test/pricing", "https://a.test/blog"]
    assert out[0]["engines"] == ["ddg"] and out[0]["rerank_score"] == 0.9
    assert "rerank_score" not in res[0]  # inputs untouched


def test_purpose_texts_from_config():
    assert rerank.purpose_text("demand", problem="late invoices").endswith("this problem: late invoices")
    assert rerank.purpose_text("competitors", product_type="invoice templates", audience="freelancers") == \
        "A product that offers invoice templates for freelancers"
    assert llm.resolve("reranker").model.name == "BAAI/bge-reranker-v2-m3"


def _weights_cached(repo: str) -> bool:
    home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    return os.path.isdir(os.path.join(home, "hub", "models--" + repo.replace("/", "--")))


@pytest.mark.skipif(importlib.util.find_spec("torch") is None or not _weights_cached("lytang/MiniCheck-Flan-T5-Large"),
                    reason="torch or MiniCheck weights not installed")
def test_minicheck_real(monkeypatch):
    monkeypatch.setenv("ROLE_CLAIM_CHECKER", "minicheck-flan-t5")
    spec = llm.resolve("claim_checker")
    src = "Posted by mira: I lose hours every month chasing late invoices."
    hi, lo = claim_checker.minicheck_scores(spec, "A freelancer loses hours chasing late invoices.", src)[0], \
        claim_checker.minicheck_scores(spec, "A freelancer earns $10,000 a month.", src)[0]
    assert hi > 0.5 > lo


def test_granite_guard_loops_criteria_and_stops_at_first_yes(monkeypatch):
    from app.services import guard
    monkeypatch.setenv("ROLE_POLICY_GUARD", "granite-guardian-8b")
    asked = []

    def backend(model, messages, schema, t):
        crit = messages[0]["content"]
        asked.append(crit)
        risky = "testimonial" in crit and "happy-customer blurbs" in messages[1]["content"]
        return ("<score> yes </score>" if risky else "no"), 5, 1
    llm.set_backend(backend)
    try:
        bad = guard.check("Could you draft a handful of happy-customer blurbs we can show on the page?", run_id="r-g")
        n_bad = len(asked)
        ok = guard.check("Draft a launch email for my template pack")
    finally:
        llm.set_backend(None)
    assert not bad.allowed and "fabricated_social_proof" in bad.reason and n_bad == 1
    assert ok.allowed and len(asked) == n_bad + len(guard._criteria())
    from app.services import decision_log
    entry = [e for e in decision_log.read("r-g") if e["action"] == "policy_refusal"][0]
    assert "criterion:fabricated_social_proof" in entry["rule_ids"]


def test_granite_guard_rules_first_and_chunks(monkeypatch):
    from app.services import guard
    monkeypatch.setenv("ROLE_POLICY_GUARD", "granite-guardian-8b")
    sizes = []
    llm.set_backend(lambda m, msgs, s, t: (sizes.append(len(msgs[1]["content"])) or "no", 1, 1))
    try:
        assert guard.check("Write 50 five-star reviews for my product").layer == "rules" and not sizes
        assert guard.check("word " * 3000).allowed
    finally:
        llm.set_backend(None)
    assert max(sizes) <= guard.CHUNK_CHARS and len(sizes) == len(guard._criteria()) * 3
    assert guard.granite_answer("<think>maybe yes</think> No") is False
    assert guard.granite_answer("garbage") is None

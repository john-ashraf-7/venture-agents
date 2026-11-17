"""Free code checks on model output: quotes on the page, keywords from the brief, verdict-first explanations."""
import json

from app import gates, llm
from app.agents import gate_explainer, planner
from app.models import Brief, PageExtract, SearchTerms, Verdict
from app.services import decision_log, keywords, reader

PAGE = "Posted by mira: I don’t know what to write in the “reminder” email. Price: $29 one-time. Ofﬁce Kit"


def test_quote_normalisation_ignores_typography():
    assert reader._norm("I don't know what to write in the \"reminder\" email") in reader._norm(PAGE)
    assert reader._norm("Office Kit") in reader._norm(PAGE)  # NFKC folds the ﬁ ligature


def test_off_page_values_dropped_and_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    ex = PageExtract(page_kind="forum", product_name="Invoice Wizard", price_text="$29 one-time",
                     problem_statements=[{"quote": "I don't know what to write in the reminder email"},
                                         {"quote": "I hate chasing clients every week"}])
    out = reader.keep_only_page_words(ex, PAGE, run_id="r-quote", url="https://example.test/p")
    assert [q.quote for q in out.problem_statements] == ["I don't know what to write in the reminder email"]
    assert out.product_name is None and out.price_text == "$29 one-time"
    drops = [e for e in decision_log.read("r-quote") if e["action"] == "quote_not_found"]
    assert sorted(e["value"] for e in drops) == ["I hate chasing clients every week", "Invoice Wizard"]
    assert all(e["sources"] == ["https://example.test/p"] and e["model"] is None for e in drops)


BRIEF = Brief(idea="Payment reminder email templates for freelance designers whose clients pay invoices late",
              product_type="template pack", target_market="freelance designers")


def test_keywords_close_variants_pass():
    ok = SearchTerms(problem="late invoice", audience="freelance designer", product_type="templates",
                     synonyms=["payment reminders", "clients paying late"])
    assert keywords.off_brief_terms(ok, BRIEF) == []


def test_keywords_off_brief_detected_and_fallback_uses_brief_phrases():
    bad = SearchTerms(problem="cash flow crisis", audience="small business owners", product_type="template pack",
                      synonyms=["accounting software", "late invoices"])
    assert set(keywords.off_brief_terms(bad, BRIEF)) == {"cash flow crisis", "small business owners", "accounting software"}
    fixed, replaced = keywords.fallback(bad, BRIEF)
    assert keywords.off_brief_terms(fixed, BRIEF) == []
    assert fixed.audience == "freelance designers" and fixed.product_type == "template pack"
    assert "late invoices" in fixed.synonyms and len(replaced) == 3


def _plan_backend(terms_seq, calls):
    def backend(model, messages, schema, t):
        calls.append(messages)
        terms = terms_seq[min(len(calls) - 1, len(terms_seq) - 1)]
        return json.dumps({"hours_low": 1, "hours_high": 2, "cost_low_usd": 0, "cost_high_usd": 10,
                           "required_skills": [], "search_terms": terms}), 5, 5
    return backend


def test_planner_retries_once_then_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    off = {"problem": "crypto taxes", "audience": "day traders", "product_type": "course", "synonyms": []}
    calls: list = []
    llm.set_backend(_plan_backend([off], calls))
    try:
        plan = planner.estimate("r-kw", BRIEF, [])
    finally:
        llm.set_backend(None)
    assert len(calls) == 2 and "not in the brief" in calls[1][-1]["content"]
    assert keywords.off_brief_terms(plan.search_terms, BRIEF) == []
    assert any(e["action"] == "keywords_fallback_to_brief" for e in decision_log.read("r-kw"))


def test_planner_retry_fixes_keywords(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    off = {"problem": "crypto taxes", "audience": "day traders", "product_type": "course", "synonyms": []}
    good = {"problem": "late invoice payments", "audience": "freelance designers", "product_type": "email templates", "synonyms": []}
    calls: list = []
    llm.set_backend(_plan_backend([off, good], calls))
    try:
        plan = planner.estimate("r-kw2", BRIEF, [])
    finally:
        llm.set_backend(None)
    assert len(calls) == 2 and plan.search_terms.problem == "late invoice payments"


def _explainer_backend(texts, calls):
    def backend(model, messages, schema, t):
        calls.append(messages)
        return json.dumps({"text": texts[min(len(calls) - 1, len(texts) - 1)]}), 5, 5
    return backend


def test_verdict_first_check():
    assert gate_explainer.verdict_first_ok("Recommendation: STOP. Evidence is thin.", Verdict.STOP)
    assert gate_explainer.verdict_first_ok("PIVOT BACK to discovery, because demand is low.", Verdict.PIVOT_BACK)
    assert not gate_explainer.verdict_first_ok("The evidence is thin, so STOP.", Verdict.STOP)
    assert not gate_explainer.verdict_first_ok("GO or STOP? STOP.", Verdict.GO)
    assert not gate_explainer.verdict_first_ok("GOOD news first.", Verdict.GO)


def test_explainer_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls: list = []
    llm.set_backend(_explainer_backend(["Demand is weak overall.", "STOP. Only 2 demand signals were found."], calls))
    try:
        text = gate_explainer.explain(None, gates.GateResult(gate="desk_evidence", verdict=Verdict.STOP, reasons=["x"]), {})
    finally:
        llm.set_backend(None)
    assert len(calls) == 2 and text.startswith("STOP.")


def test_explainer_prepends_after_two_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls: list = []
    llm.set_backend(_explainer_backend(["Demand looks promising, so GO ahead."], calls))
    try:
        text = gate_explainer.explain(None, gates.GateResult(gate="desk_evidence", verdict=Verdict.REPEAT, reasons=["x"]), {})
    finally:
        llm.set_backend(None)
    assert len(calls) == 3  # first reply + 2 corrective retries
    assert text.startswith("Recommendation: REPEAT. ")

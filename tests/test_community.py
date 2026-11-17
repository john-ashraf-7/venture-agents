"""Community demand evidence: official-API posts become pages without an LLM read, bot-check pages never reach
the reader, competitor queries keep the topic, and the demand classifier rejects off-topic or advice quotes."""
import json
from pathlib import Path

from app.agents import demand_classifier, market_researcher
from app.models import SearchTerms
from app.orchestrator.orchestrator import community_demand
from app.services import community, reader, search
from app.services.search import queries

ROOT = Path(__file__).resolve().parent.parent
TODO_BRIEF = json.loads((ROOT / "evals/briefs/crowded_todo_app.json").read_text())["founder_input"]
TODO_TERMS = SearchTerms(problem="to-do list", audience="everyone", product_type="to-do list template pack",
                         synonyms=["task list"])


# ------------------------------------------------------------------ Step 1: community APIs, no scraping
def test_community_search_is_off_in_fixture_mode():
    assert community.search_community(["late invoices"], "freelancers", 5) == []


def test_reddit_skipped_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert community.reddit("late invoices", 5) == []


def test_community_posts_become_pages_with_api_quote_and_date(monkeypatch):
    post = community.CommunityPost(
        source="hackernews", url="https://news.ycombinator.com/item?id=1", author_handle_hash=community.hash_handle("pg"),
        created_at="2026-10-02", score=3, thread_title="Ask HN: invoicing",
        text="Great thread. I lose two days a month chasing late invoice payments from clients. Any tips?")
    monkeypatch.setattr(community, "search_community", lambda *a, **k: [post])
    pages = market_researcher.community_pages("r1", SearchTerms(problem="late invoice payments", audience="freelancers",
                                                                product_type="templates"))
    assert len(pages) == 1
    p = pages[0]
    ps = p["extract"]["problem_statements"][0]
    assert ps["quote"] in p["text"] and ps["quote"].startswith("I lose two days") and ps["date"] == "2026-10-02"
    assert p["origin"] == "community-api (hackernews)" and p["provider"] == "hackernews"
    assert community_demand(ps["quote"], p, {"community_domains": ["news.ycombinator.com"]})
    assert "pg" not in json.dumps(p)


def test_strip_html_keeps_exact_words():
    assert community.strip_html("<p>I hate my <b>to-do</b> app &amp; lists</p>") == "I hate my to-do app & lists"


def test_bot_check_page_is_never_read(monkeypatch):
    """A saved Reddit challenge page, served from a forum host, goes through the gather path: 0 pages read, 0 claims."""
    html = (ROOT / "evals/fixtures/pages/reddit_bot_check.html").read_text()
    assert reader.quality(reader.html_to_text(html), html) == "bot_check"
    urls = ["https://forum.example.test/t/1", "https://www.reddit.com/r/productivity/comments/1/x/"]
    asked = []
    monkeypatch.setattr(reader, "_fixture_page", lambda u: asked.append(u) or html)
    monkeypatch.setattr(search, "search", lambda q, n, purpose, run_id=None: {
        "results": [{"url": u, "title": "t", "snippet": "s"} for u in urls], "origin": "fixture", "note": "test"})

    def no_read(*a, **k):
        raise AssertionError("the reader must not see a bot-check page")
    monkeypatch.setattr(reader, "read", no_read)
    out = market_researcher.gather("r1", [("demand", "to-do list frustrated")])
    assert out["pages"] == []
    assert market_researcher.extract_claims("r1", None, out["pages"]).claims == []
    assert not any(e["action"] == "read_page_isolated" for e in __import__("app.services.decision_log", fromlist=["x"]).read("r1"))
    from app.services import decision_log
    log = decision_log.read("r1")
    assert any(e["action"] == "fetch_rejected" and e.get("reason") == "bot_check" for e in log)
    assert asked == ["https://forum.example.test/t/1"]  # reddit.com HTML is never requested


def test_no_site_reddit_demand_queries():
    built = queries.build(TODO_TERMS, "demand", limit=10)
    assert built and not any("site:" in q for q in built)


# ------------------------------------------------------------------ Step 2: competitor queries keep the topic
def test_crowded_todo_competitor_queries_name_the_problem():
    built = queries.build(TODO_TERMS, "competitors", limit=4)
    assert built and all(("to-do" in q.lower() or "todo" in q.lower()) for q in built), built
    assert not any("everyone" in q.lower() for q in built)
    assert all(queries.lint(q, idea=TODO_BRIEF["idea"], purpose="competitors", terms=TODO_TERMS) is None for q in built)
    planned = market_researcher.plan_queries("r1", TODO_TERMS, TODO_BRIEF["idea"], {"competitors": ""})
    assert planned and all("to-do" in q for _, q in planned)


def test_lint_rejects_competitor_query_without_problem_keyword():
    assert queries.lint("template pack for everyone", purpose="competitors", terms=TODO_TERMS)
    assert queries.lint("best task list app", purpose="competitors", terms=TODO_TERMS) is None  # synonym


# ------------------------------------------------------------------ Step 3: relevance before counting
def _classify(quote):
    return demand_classifier.classify(quote, problem="to-do list", idea=TODO_BRIEF["idea"], run_id="r1",
                                      url="https://superuser.com/q/1")


def test_sharepoint_list_question_is_not_todo_demand():
    c = _classify("I am looking for how I can create a list in a modern sharepoint site with custom columns.")
    assert not demand_classifier.counts(c)


def test_advice_reply_is_not_demand():
    c = _classify("You should just use a paper notebook for your to-do list, it works better than any app.")
    assert not demand_classifier.counts(c)


def test_first_person_todo_problem_counts_and_rejects_are_logged():
    assert demand_classifier.counts(_classify("I keep losing track of my to-do list across three different apps."))
    assert not demand_classifier.counts(_classify("Try a bullet journal for your to-do list."))
    from app.services import decision_log
    log = decision_log.read("r1")
    assert any(e["action"] == "demand_rejected" and e["reason"] for e in log)
    assert any(e["action"] == "classify_demand" for e in log)


# ------------------------------------------------------------------ Tavily budget and domain filters
def test_tavily_budget_and_domain_filters(monkeypatch):
    from app.services.search import tavily
    demand = tavily._options("demand", 5)
    assert {"reddit.com", "news.ycombinator.com", "stackexchange.com"} <= set(demand["include_domains"])
    comp = tavily._options("competitors", 5)
    assert "include_domains" not in comp and "canva.com" in comp["exclude_domains"]
    monkeypatch.setitem(tavily._SPENT, "rb", 12)
    monkeypatch.setenv("SEARCH_MODE", "live")
    monkeypatch.setenv("TAVILY_API_KEY", "test-placeholder")
    res = tavily.search("to-do list app", 5, "competitors", run_id="rb")
    assert res["results"] == [] and "budget" in res["note"]


def test_stackexchange_always_softwarerecs_plus_brief_sites():
    assert community.stackexchange_sites("late invoice payments freelancers")[:2] == ["softwarerecs", "freelancing"]
    assert community.stackexchange_sites("to-do list everyone") == ["softwarerecs", "webapps"]
    assert community.stackexchange_sites("zzz")[0] == "softwarerecs"

"""Tavily is OPTIONAL: no key (the default) or SEARCH_PROVIDER=searxng never calls it, and a Tavily error falls back
to SearXNG for that query with the reason in the note."""
import httpx
import pytest

from app.services import search as s
from app.services.search import tavily


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"results": [{"url": "https://example.com/a", "title": "A", "content": "a", "engines": ["bing"]}]}


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("SEARCH_MODE", "live")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("Tavily was called"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(s, "_LAST_LIVE", [0.0])


def test_default_without_key_never_calls_tavily(live, monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert not tavily.enabled()
    out = s.search("invoice templates", 5, "competitors")
    assert out["origin"] == "live" and out["note"] == "live search (SearXNG)"


def test_searxng_provider_ignores_key(live, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "searxng")
    monkeypatch.setenv("TAVILY_API_KEY", "placeholder")
    assert s.search("invoice templates", 5, "demand")["note"] == "live search (SearXNG)"


def test_auto_with_key_falls_back_when_out_of_credits(live, monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "placeholder")

    def post(url, **k):
        resp = httpx.Response(432, request=httpx.Request("POST", url))
        raise httpx.HTTPStatusError("limit", request=resp.request, response=resp)

    monkeypatch.setattr(httpx, "post", post)
    out = s.search("invoice templates", 5, "competitors")
    assert out["origin"] == "live" and out["results"][0]["url"] == "https://example.com/a"
    assert "fallback: Tavily HTTP 432 out of credits" in out["note"]
    assert ["tavily", "HTTP 432 out of credits"] in out["unresponsive"]


def test_tavily_path_returns_same_shape(live, monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "placeholder")
    sent = {}

    class R(_Resp):
        def json(self):
            return {"results": [{"url": "https://www.reddit.com/r/x/1", "title": "t", "content": "c"}]}

    def post(url, json, headers, timeout):
        sent.update(json)
        return R()

    monkeypatch.setattr(httpx, "post", post)
    out = s.search("late invoice payments", 5, "demand")
    assert set(out) == {"query", "results", "origin", "note", "engines", "unresponsive"}
    assert out["results"][0]["engines"] == ["tavily"] and "reddit.com" in sent["include_domains"]


def test_blocked_community_page_is_read_through_tavily_extract(monkeypatch):
    from app.agents import market_researcher as mr
    from app.services.search import tavily
    monkeypatch.setattr(tavily, "enabled", lambda: True)
    text = "I keep chasing clients for weeks after sending invoices. " * 20
    monkeypatch.setattr(tavily, "extract", lambda urls: {u: text for u in urls})
    fetched = [{"url": "https://www.reddit.com/r/freelance/comments/1/x/", "ok": False, "reason": "http_403", "text": ""},
               {"url": "https://example.org/a", "ok": True, "reason": None, "text": "ok " * 200}]
    out = mr._extract_failed("run_test_extract", "demand", fetched, {"max_pages": 1, "page_chars": 6000})
    assert out[0]["ok"] and out[0]["origin"] == "tavily-extract" and out[0]["text"].startswith("I keep chasing")
    monkeypatch.setattr(tavily, "enabled", lambda: False)
    assert mr._extract_failed("run_test_extract", "demand", fetched, {"max_pages": 1, "page_chars": 6000}) == fetched


def test_clean_markdown_drops_images_and_link_targets():
    from app.agents.market_researcher import clean_markdown
    md = "[r/freelance](https://www.reddit.com/r/freelance/)•8y ago\n\n\n\n![avatar](https://x/y.png)I was  paid late."
    assert clean_markdown(md).split() == ["r/freelance•8y", "ago", "I", "was", "paid", "late."]
    assert "https://" not in clean_markdown(md)


def test_search_raw_text_is_ignored_without_a_key(monkeypatch):
    from app.agents import market_researcher as mr
    from app.services.search import tavily
    monkeypatch.setattr(tavily, "enabled", lambda: False)
    fetched = [{"url": "https://www.reddit.com/r/a/comments/1/x/", "ok": False, "reason": "http_403", "text": ""}]
    raw = {"https://www.reddit.com/r/a/comments/1/x/": "I keep chasing late invoices every month. " * 20}
    assert mr._extract_failed("run_test_raw", "demand", fetched, {"max_pages": 5, "page_chars": 6000}, raw) == fetched


def test_claims_are_extracted_in_batches_and_empty_pages_skipped(monkeypatch):
    from app.agents import market_researcher as mr
    from app.models import ClaimList
    calls = []
    monkeypatch.setattr(mr.base, "run", lambda *a, **k: calls.append(len(a[5]["page_extracts"])) or ClaimList(claims=[]))
    full = {"problem_statements": [{"quote": "I was paid late", "date": "2026-01-01"}]}
    pages = [{"url": f"https://ex.org/{i}", "retrieved_at": "t", "extract": full} for i in range(9)]
    pages.append({"url": "https://ex.org/empty", "retrieved_at": "t", "extract": {"page_kind": "other"}})
    brief = type("B", (), {"idea": "idea", "target_market": "market"})()
    mr.extract_claims(None, brief, pages)
    assert calls == [4, 4, 1]

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

"""Tavily is OPTIONAL: the default path and a missing key both stay on SearXNG and never call Tavily."""
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


def test_default_provider_never_calls_tavily(live, monkeypatch):
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "placeholder")
    out = s.search("invoice templates", 5, "competitors")
    assert out["origin"] == "live" and out["note"] == "live search (SearXNG)"


def test_missing_key_falls_back_to_searxng(live, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert not tavily.enabled()
    assert s.search("invoice templates", 5, "demand")["note"] == "live search (SearXNG)"


def test_tavily_path_returns_same_shape(live, monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
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

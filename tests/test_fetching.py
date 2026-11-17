"""Fetching: over-fetch, replace failures with the next candidate, record a reason for every rejection."""
import httpx

from app.services import reader

GOOD = "<html><body><article>" + "".join(
    f"<p>Paragraph {i}: freelancer number {i} explains how late invoice number {i * 7} was finally paid.</p>"
    for i in range(20)) + "</article></body></html>"
PAGES = {
    "https://a.test/404": (404, ""),
    "https://b.test/captcha": (200, "<html><div class='cf-chl'>Please verify you are human</div></html>"),
    "https://c.test/short": (200, "<html><body><p>Hi</p></body></html>"),
    "https://d.test/good": (200, GOOD),
    "https://e.test/good": (200, GOOD),
    "https://f.test/extra": (200, GOOD),
}


def test_fetch_many_replaces_failures_and_stops_early(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "live")
    real = httpx.AsyncClient

    def client(**kw):
        kw.pop("headers", None)
        return real(transport=httpx.MockTransport(lambda r: httpx.Response(
            PAGES[str(r.url)][0], text=PAGES[str(r.url)][1], headers={"content-type": "text/html"})), **kw)
    monkeypatch.setattr(reader.httpx, "AsyncClient", client)
    got = reader.fetch_many(list(PAGES), 6000, want=2, concurrency=2)
    reasons = {p["url"]: p["reason"] for p in got}
    assert reasons["https://a.test/404"] == "http_404"
    assert reasons["https://b.test/captcha"] == "bot_check"
    assert reasons["https://c.test/short"] == "too_short"
    assert [p["url"] for p in got if p["ok"]] == ["https://d.test/good", "https://e.test/good"]
    # concurrency 2: the last batch may fetch one extra page, but only the first 2 good pages are kept


def test_structured_prices_rescue_a_javascript_pricing_page():
    html = ('<html><script>document.addEventListener("x", f)</script><div id="__next"></div>'
            '<script type="application/ld+json">{"@type":"Product","name":"Kit","offers":{"@type":"Offer",'
            '"price":"29.00","priceCurrency":"USD"}}</script></html>')
    assert reader.structured_prices(html) == ["Kit: 29.00 USD"]
    assert reader.quality(reader.html_to_text(html), html) in ("js_required", "too_short")

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.connectors.notino_public import NotinoPublicStorefrontConnector
from scrapers.notino import scraper


class FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_discovery_uses_only_direct_search_requests(monkeypatch):
    session = FakeSession()
    requests_seen = []

    class Response:
        status_code = 200
        text = "<html>direct search result</html>"

    monkeypatch.setattr(scraper, "_new_session", lambda: session)
    monkeypatch.setattr(
        scraper, "_search_urls",
        lambda query: ["https://www.notino.fr/search.asp?exps=Dior"],
    )

    def direct_request(_session, url, reader=False):
        requests_seen.append((url, reader))
        assert reader is False
        return Response()

    monkeypatch.setattr(scraper, "_request", direct_request)
    monkeypatch.setattr(
        scraper, "extract_candidates_from_html",
        lambda html, query: [{
            "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123/",
            "name": "Dior Sauvage Eau de Parfum 100 ml",
            "brand": "Dior",
        }],
    )
    monkeypatch.setattr(
        scraper, "_discover",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("proxy-enabled discovery must not run")),
    )
    monkeypatch.setattr(
        scraper, "_reader_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reader proxy must not run")),
    )

    rows, diagnostics = NotinoPublicStorefrontConnector._discover_query("Dior Sauvage Eau de Parfum")

    assert len(rows) == 1
    assert rows[0]["brand"] == "Dior"
    assert requests_seen == [("https://www.notino.fr/search.asp?exps=Dior", False)]
    assert diagnostics["reader"] == []
    assert diagnostics["sitemap_used"] is False
    assert session.closed


def test_product_fetch_uses_exact_direct_product_page_without_reader_proxy(monkeypatch):
    session = FakeSession()
    product_url = "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123/"

    class Response:
        status_code = 200
        url = product_url
        text = "<html>direct product page</html>"

    requests_seen = []
    monkeypatch.setattr(scraper, "_new_session", lambda: session)

    def direct_request(_session, url, reader=False):
        requests_seen.append((url, reader))
        assert reader is False
        return Response()

    monkeypatch.setattr(scraper, "_request", direct_request)
    monkeypatch.setattr(
        scraper, "_parse_product",
        lambda url, html, query: {
            "name": "Dior Sauvage Eau de Parfum 100 ml",
            "brand": "Dior",
            "size_ml": 100,
            "concentration": "Eau de Parfum",
            "price": "89.90 €",
            "price_num": 89.90,
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in stock",
            "url": url,
        },
    )
    monkeypatch.setattr(
        scraper, "_reader_product",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("reader proxy must not run")),
    )

    connector = NotinoPublicStorefrontConnector()
    result = connector._fetch_sync(
        product_url,
        {"url": product_url, "name": "Dior Sauvage Eau de Parfum 100 ml", "query": "Dior Sauvage"},
    )

    assert result is not None
    assert result["brand"] == "Dior"
    assert result["currency"] == "EUR"
    assert result["currency_explicit"] is True
    assert result["availability"] == "in_stock"
    assert result["source"] == "notino_public_storefront"
    assert result["url"] == product_url
    assert requests_seen == [(product_url, False)]
    assert session.closed


def test_direct_discovery_keeps_403_blocked_and_does_not_try_proxy(monkeypatch):
    import requests

    session = FakeSession()
    monkeypatch.setattr(scraper, "_new_session", lambda: session)
    monkeypatch.setattr(
        scraper, "_search_urls",
        lambda query: ["https://www.notino.fr/search.asp?exps=Dior"],
    )

    def blocked(_session, url, reader=False):
        assert reader is False
        response = SimpleNamespace(status_code=403)
        error = requests.HTTPError("403 Forbidden", response=response)
        raise error

    monkeypatch.setattr(scraper, "_request", blocked)
    monkeypatch.setattr(
        scraper, "_reader_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("proxy fallback is forbidden")),
    )

    rows, diagnostics = NotinoPublicStorefrontConnector._discover_query("Dior Sauvage")

    assert rows == []
    assert diagnostics["direct"][0]["status"] == 403
    assert diagnostics["reader"] == []
    assert diagnostics["sitemap_used"] is False
    assert session.closed

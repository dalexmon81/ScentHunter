"""Regression tests for bounded Notino external-discovery fallback."""

from backend.scrapers.notino import legacy_public, scraper


def test_price_bearing_search_result_returns_before_blocked_product_browser(monkeypatch):
    candidate = {
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "price_hint": "89,90€",
        "score": 100,
    }
    monkeypatch.setattr(
        legacy_public,
        "_discover",
        lambda query, session: ([candidate], {"primary_channel": "bing-rss"}),
    )
    monkeypatch.setattr(
        legacy_public,
        "_browser_fetch_products",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("price-bearing result should not wait on product browser")
        ),
    )

    rows = legacy_public.search("Dior Sauvage Eau de Parfum 100 ml")

    assert len(rows) == 1
    assert rows[0]["url"] == candidate["url"]
    assert rows[0]["price"] == "89,90€"
    assert rows[0]["price_source"] == "external_search_snippet"

def test_discovery_uses_external_rss_before_blocked_store_browser(monkeypatch):
    candidate = {
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "price_hint": "89,90€",
        "score": 100,
    }
    monkeypatch.setattr(
        legacy_public,
        "_bing_rss",
        lambda query, session: ([candidate], {"engine": "bing-rss", "candidate_count": 1}),
    )
    monkeypatch.setattr(
        legacy_public,
        "_browser_search",
        lambda query: (_ for _ in ()).throw(
            AssertionError("Notino browser must not run before independent RSS discovery")
        ),
    )
    candidates, report = legacy_public._discover(
        "Dior Sauvage Eau de Parfum 100 ml",
        object(),
    )
    assert candidates == [candidate]
    assert report["primary_channel"] == "bing-rss"



def test_search_adapter_uses_public_discovery_without_calling_cj_feed(monkeypatch):
    expected = [{
        "store": "notino",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "price": "89,90€",
    }]
    monkeypatch.setattr(legacy_public, "search", lambda query: expected)
    monkeypatch.setattr(
        "backend.scrapers.notino.affiliate_feed.search_feed",
        lambda query: (_ for _ in ()).throw(
            AssertionError("CJ feed must not be required for public discovery")
        ),
    )

    report = scraper.search("Dior Sauvage Eau de Parfum 100 ml")

    assert report["status"] == "success"
    assert report["verified"] is True
    assert report["results"] == expected
    assert report["details"]["source"] == "notino_public_product_pages"
    assert report["details"]["feed_required"] is False

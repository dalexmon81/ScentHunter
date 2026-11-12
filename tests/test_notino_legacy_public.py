"""Regression tests for bounded Notino external-discovery fallback."""

from backend.scrapers.notino import legacy_public, scraper as notino_scraper


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


def test_descriptive_notino_product_slug_without_numeric_id_is_accepted():
    url = "https://www.notino.fr/rayhaan/aquatica-eau-de-parfum-pour-homme/"
    assert legacy_public.lookslikeproducturl(url)
    assert notino_scraper.lookslikeproducturl(url)


def test_generic_notino_brand_product_root_without_product_identity_is_rejected():
    url = "https://www.notino.fr/rayhaan/aquatica/"
    assert not legacy_public.lookslikeproducturl(url)
    assert not notino_scraper.lookslikeproducturl(url)


def test_legacy_notino_product_id_url_remains_accepted():
    url = "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/"
    assert legacy_public.lookslikeproducturl(url)

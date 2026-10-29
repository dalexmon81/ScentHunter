"""Contract tests for the Notino public storefront adapter."""

import json

from backend.scrapers.notino import scraper


def test_candidate_url_admission_preserves_market_and_rejects_navigation():
    assert scraper._allowed_url(
        "/dior/sauvage-eau-de-parfum/", "https://www.notino.fr"
    ) == "https://www.notino.fr/dior/sauvage-eau-de-parfum/"
    assert scraper._allowed_url(
        "/parfums/", "https://www.notino.fr"
    ) is None
    assert scraper._allowed_url(
        "https://example.com/dior/sauvage/", "https://www.notino.fr"
    ) is None


def test_product_parser_extracts_price_size_concentration_and_market_url():
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Sauvage Eau de Parfum 100 ml",
        "brand": {"@type": "Brand", "name": "Dior"},
        "image": "https://cdn.notinoimg.com/dior/sauvage.jpg",
        "offers": {
            "@type": "Offer",
            "price": "99.90",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        },
    }
    html = f"""
    <html><head><script type="application/ld+json">{json.dumps(product)}</script></head>
    <body><h1>Sauvage Eau de Parfum 100 ml</h1></body></html>
    """
    row = scraper._parse_product(
        "https://www.notino.fr/dior/sauvage-eau-de-parfum/",
        html,
        "Dior Sauvage",
    )
    assert row is not None
    assert row["shop"] == "Notino"
    assert row["brand"] == "Dior"
    assert row["price_num"] == 99.90
    assert row["size_ml"] == 100
    assert row["concentration"] == "Eau de Parfum"
    assert row["available"] is True
    assert row["url"].startswith("https://www.notino.fr/")


def test_product_parser_rejects_wrong_query_and_missing_price():
    wrong = {
        "@type": "Product",
        "name": "Blue Jeans Eau de Toilette 75 ml",
        "brand": {"name": "Versace"},
        "offers": {"price": "22.00", "priceCurrency": "EUR"},
    }
    html = f'<script type="application/ld+json">{json.dumps(wrong)}</script><h1>Blue Jeans Eau de Toilette 75 ml</h1>'
    assert scraper._parse_product(
        "https://www.notino.fr/versace/blue-jeans/", html, "Dior Sauvage"
    ) is None

    no_price = {**wrong, "name": "Sauvage Eau de Parfum 100 ml", "brand": {"name": "Dior"}, "offers": {}}
    no_price_html = f'<script type="application/ld+json">{json.dumps(no_price)}</script><h1>Sauvage Eau de Parfum 100 ml</h1>'
    assert scraper._parse_product(
        "https://www.notino.fr/dior/sauvage/", no_price_html, "Dior Sauvage"
    ) is None


def test_price_parser_handles_european_decimal_and_thousands_separators():
    assert scraper._price("99,90 €") == 99.90
    assert scraper._price("1.299,90 €") == 1299.90
    assert scraper._price("1,299.90 EUR") == 1299.90


def test_search_returns_verified_report_for_empty_query():
    report = scraper.search("  ")
    assert report["status"] == "success"
    assert report["verified"] is True
    assert report["results"] == []


def test_notino_live_search_is_france_only():
    assert scraper.MARKETS == (
        ("https://www.notino.fr", "fr-FR,fr;q=0.9,en;q=0.7"),
    )
    assert all("notino.de" not in base for base, _language in scraper.MARKETS)


def test_search_falls_back_to_public_search_when_feed_has_no_match(monkeypatch):
    from backend.scrapers.notino import affiliate_feed

    monkeypatch.setattr(
        affiliate_feed,
        "search_feed",
        lambda query: {
            "status": "success", "verified": True, "results": [],
            "error": None, "details": {"source": "cj_viv_authorized_xml"},
        },
    )
    expected = [{
        "shop": "Notino",
        "store": "notino",
        "brand": "Dior",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "price": "89.90 €",
        "price_num": 89.90,
        "currency": "EUR",
        "available": True,
        "availability": "In stock",
        "image": None,
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/",
    }]
    monkeypatch.setattr(
        scraper, "_search_market",
        lambda query, base, language: (expected, [], 1),
    )

    report = scraper.search("Dior Sauvage Eau de Parfum")

    assert report["status"] == "success"
    assert report["verified"] is True
    assert report["results"] == expected
    assert report["details"]["source"] == "notino_public_search"
def test_search_does_not_fallback_when_feed_has_fresh_matching_offer(monkeypatch):
    from backend.scrapers.notino import affiliate_feed, legacy_public

    expected = [{
        "store": "notino", "name": "Dior Sauvage Eau de Parfum 100 ml",
        "price": "89.90 €", "price_num": 89.90,
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/",
    }]
    monkeypatch.setattr(
        affiliate_feed,
        "search_feed",
        lambda query: {
            "status": "success", "verified": True, "results": expected,
            "error": None, "details": {"source": "cj_viv_authorized_xml"},
        },
    )
    monkeypatch.setattr(
        legacy_public, "search",
        lambda query: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    report = scraper.search("Dior Sauvage Eau de Parfum")

    assert report["results"] == expected
    assert report["details"]["source"] == "cj_viv_authorized_xml"


def test_generic_notino_discovery_tries_current_france_search_route_first():
    from backend.scrapers.notino import legacy_public

    urls = legacy_public._search_urls("Dior Sauvage")
    assert urls[0].startswith("https://www.notino.fr/search/?exps=")
    assert "lastPage=1-0-1" in urls[0]
    assert any(url.startswith("https://www.notino.fr/search.asp?exps=") for url in urls)


def test_feed_search_requires_exact_parsed_size_when_query_specifies_size(monkeypatch):
    import sys
    from backend.scrapers.notino import affiliate_feed
    from backend import catalog_engine

    monkeypatch.setitem(sys.modules, "catalog_engine", catalog_engine)

    base = {
        "url": "https://www.notino.fr/french-avenue/liquid-brun-limited-edition/",
        "variant_url": "https://www.notino.fr/french-avenue/liquid-brun-limited-edition/",
        "name": "French Avenue Liquid Brun Limited Edition 150 ml",
        "brand": "French Avenue",
        "image": None,
        "concentration": "Extrait de Parfum",
        "gtin": None,
        "sku": None,
        "price": 49.90,
        "currency": "EUR",
        "availability": "in_stock",
        "fetched_at": 9999999999,
        "active": 1,
    }
    rows = [
        {**base, "size_ml": None, "price": 39.90},
        {**base, "size_ml": 100.0, "price": 29.90},
        {**base, "size_ml": 150.0, "price": 49.90},
    ]

    class Cursor:
        def fetchall(self):
            return rows

    class Connection:
        def execute(self, *_args):
            return Cursor()
        def close(self):
            pass

    monkeypatch.setattr(catalog_engine, "db", lambda: Connection())

    report = affiliate_feed.search_feed("French Avenue Liquid Brun Limited Edition 150 ml")

    assert len(report["results"]) == 1
    assert report["results"][0]["size_ml"] == 150.0
    assert report["results"][0]["price_num"] == 49.90



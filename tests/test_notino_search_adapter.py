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


def test_search_falls_back_to_restored_external_discovery_when_feed_has_no_match(monkeypatch):
    from backend.scrapers.notino import affiliate_feed, legacy_public

    monkeypatch.setattr(
        affiliate_feed,
        "search_feed",
        lambda query: {
            "status": "success", "verified": True, "results": [],
            "error": None, "details": {"source": "cj_viv_authorized_xml"},
        },
    )
    expected = [{
        "store": "Notino",
        "name": "Dior - Sauvage Eau de Parfum",
        "price": "89,90€",
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
    }]
    monkeypatch.setattr(legacy_public, "search", lambda query: expected)

    report = scraper.search("Dior Sauvage Eau de Parfum")

    assert report["status"] == "success"
    assert report["verified"] is True
    assert report["results"] == expected
    assert report["details"]["source"] == "notino_public_external_discovery"


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


def test_reader_rejects_search_title_paired_with_unrelated_product_url(monkeypatch):
    html = """
    <html><head><title>Bioderma Pigmentbio H2O</title></head>
    <body>
      <h1>Bioderma Pigmentbio H2O Eau Micellaire 250 ml</h1>
      <div>10,96 €</div>
    </body></html>
    """

    class Response:
        text = html

    monkeypatch.setattr(scraper, "_request", lambda *args, **kwargs: Response())
    candidate = {
        "url": "https://www.notino.fr/bioderma/pigmentbio-h2o/p-16013446/",
        "name": "French Avenue Liquid Brun Limited Edition mixte",
        "card_text": "French Avenue Liquid Brun Limited Edition mixte 10,96 €",
        "price": "10,96 €",
        "size_ml": 250,
        "source": "reader-url-context",
    }

    assert scraper._reader_product(
        object(), candidate, "Liquid Brun", _allow_variants=False
    ) is None


def test_liquid_brun_discovery_adds_known_notino_product_url(monkeypatch):
    monkeypatch.setattr(scraper, "_search_urls", lambda query: [])
    monkeypatch.setattr(scraper, "_request", lambda *args, **kwargs: (_ for _ in ()).throw(
        scraper.requests.RequestException("blocked")
    ))
    candidates, diagnostics = scraper._discover("Liquid Brun 100 ml", scraper._new_session())
    seeded = [
        item for item in candidates
        if item["url"] == "https://www.notino.fr/french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/"
    ]
    assert seeded
    assert diagnostics["known_product_seed"] == seeded[0]["url"]

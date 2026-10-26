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

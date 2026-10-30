"""Regression tests for the current Notino discovery/enrichment contract.

The scraper returns a list of independently verified product rows. These tests
exercise its current helpers instead of the retired report-dict adapter API.
"""
from backend.scrapers.notino import scraper


def test_candidate_url_admission_normalizes_market_and_rejects_navigation():
    assert scraper.normaliseurl(
        "/dior/sauvage-eau-de-parfum/p-123456/",
    ) == "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/"
    assert scraper.lookslikeproducturl(
        "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/"
    )
    assert not scraper.lookslikeproducturl("https://www.notino.fr/parfums/")
    assert not scraper.lookslikeproducturl("https://example.com/dior/sauvage/p-123456/")


def test_structured_product_evidence_extracts_eur_price_brand_size_and_stock():
    record = {
        "@type": "Product",
        "name": "Sauvage Eau de Parfum 100 ml",
        "brand": {"name": "Dior"},
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "offers": {
            "@type": "Offer",
            "price": "99.90",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        },
    }
    name, brand, url, price, size = scraper._structured_record_to_evidence(record)
    assert name == "Sauvage Eau de Parfum 100 ml"
    assert brand == "Dior"
    assert url.endswith("/p-123456/")
    assert price == "99,90€"
    assert size == 100


def test_candidate_rejects_wrong_product_and_wrong_size():
    wrong = scraper._candidate_from_evidence(
        "https://www.notino.fr/versace/blue-jeans/p-123/",
        "Blue Jeans Eau de Toilette 75 ml",
        "22,00€",
        "Dior Sauvage 100 ml",
        "test",
    )
    assert wrong is None

    wrong_size = scraper._candidate_from_evidence(
        "https://www.notino.fr/dior/sauvage/p-124/",
        "Dior Sauvage Eau de Parfum 75 ml",
        "99,90€",
        "Dior Sauvage 100 ml",
        "test",
    )
    assert wrong_size is None


def test_price_extraction_requires_euro_evidence_for_numeric_values():
    assert scraper._extract_price("Sauvage 99,90 €") == "99,90€"
    assert scraper._extract_price("EUR 89.90") == "89,90€"
    assert scraper._extract_price("Sauvage 89.90") == ""


def test_search_returns_empty_list_for_empty_query():
    assert scraper.search("  ") == []


def test_notino_live_search_is_france_only():
    assert scraper.BASE_URL == "https://www.notino.fr"
    assert scraper.SEARCH_URL.startswith("https://www.notino.fr/")
    assert "notino.de" not in scraper.BASE_URL


def test_dedupe_keeps_distinct_sizes_for_same_notino_product():
    rows = [
        {"url": "https://www.notino.fr/dior/sauvage/p-123/", "size_ml": 60, "price": "79,90€"},
        {"url": "https://www.notino.fr/dior/sauvage/p-123/", "size_ml": 100, "price": "99,90€"},
        {"url": "https://www.notino.fr/dior/sauvage/p-123/", "size_ml": 100, "price": "99,90€", "availability": True},
    ]
    result = scraper._dedupe_results(rows)
    assert len(result) == 2
    assert {row["size_ml"] for row in result} == {60, 100}
    assert next(row for row in result if row["size_ml"] == 100)["availability"] is True


def test_search_does_not_accept_unverified_search_card_for_wrong_page(monkeypatch):
    html = """
    <html><head><title>Bioderma Pigmentbio H2O</title></head>
    <body><h1>Bioderma Pigmentbio H2O Eau Micellaire 250 ml</h1><div>10,96 €</div></body></html>
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
    assert scraper._reader_product(object(), candidate, "Liquid Brun", _allow_variants=False) is None

"""Regression tests for Notino's market-specific catalog discovery rules."""

from backend import catalog_engine as catalog


def test_notino_fr_and_de_are_configured_as_separate_official_markets():
    assert catalog.STORES["notino"] == "https://www.notino.fr"
    assert catalog._discovery_bases("notino") == (
        "https://www.notino.fr",
        "https://www.notino.de",
    )
    assert catalog.STORE_LABELS["notino"] == "Notino"


def test_notino_slug_product_urls_keep_market_host_and_drop_tracking_query():
    fr = catalog._html_product_url(
        "notino",
        "https://www.notino.fr/brand/fragrance-name/?utm_source=test",
        "https://www.notino.fr/",
    )
    de = catalog._html_product_url(
        "notino",
        "https://www.notino.de/marke/duft-name/?utm_campaign=test",
        "https://www.notino.de/",
    )
    assert fr == "https://www.notino.fr/brand/fragrance-name/"
    assert de == "https://www.notino.de/marke/duft-name/"


def test_notino_rejects_non_product_and_foreign_host_urls():
    assert catalog._html_product_url(
        "notino", "https://www.notino.fr/parfums/", "https://www.notino.fr/"
    ) is None
    assert catalog._html_product_url(
        "notino", "https://example.com/brand/name/", "https://www.notino.fr/"
    ) is None


def test_notino_catalog_seeds_are_public_fragrance_navigation_pages():
    seeds = catalog.HTML_DISCOVERY_SEEDS["notino"]
    assert "https://www.notino.fr/parfums/" in seeds
    assert "https://www.notino.de/parfums/" in seeds
    assert all("p-" not in url for url in seeds)


def test_notino_listing_admission_only_accepts_catalog_navigation():
    assert catalog._html_listing_url(
        "notino", "https://www.notino.fr/parfums/", "https://www.notino.fr/"
    ) == "https://www.notino.fr/parfums/"
    assert catalog._html_listing_url(
        "notino", "https://www.notino.fr/brand/fragrance/p-123456/", "https://www.notino.fr/"
    ) is None

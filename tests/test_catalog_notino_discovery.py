"""Regression tests for market-specific catalog discovery rules."""

from backend import catalog_engine as catalog


def test_notino_is_configured_for_france_only():
    assert catalog.STORES["notino"] == "https://www.notino.fr"
    assert catalog._discovery_bases("notino") == ("https://www.notino.fr",)
    assert catalog.STORE_LABELS["notino"] == "Notino"
    assert all("notino.de" not in url for url in catalog.HTML_DISCOVERY_SEEDS["notino"])


def test_notino_slug_product_urls_keep_french_host_and_drop_tracking_query():
    fr = catalog._html_product_url(
        "notino",
        "https://www.notino.fr/brand/fragrance-name/?utm_source=test",
        "https://www.notino.fr/",
    )
    de = catalog._html_product_url(
        "notino",
        "https://www.notino.de/marke/duft-name/?utm_campaign=test",
        "https://www.notino.fr/",
    )
    assert fr == "https://www.notino.fr/brand/fragrance-name/"
    assert de is None


def test_notino_rejects_non_product_and_foreign_host_urls():
    assert catalog._html_product_url(
        "notino", "https://www.notino.fr/parfums/", "https://www.notino.fr/"
    ) is None
    assert catalog._html_product_url(
        "notino", "https://example.com/brand/name/", "https://www.notino.fr/"
    ) is None


def test_notino_catalog_seeds_are_french_fragrance_navigation_pages():
    seeds = catalog.HTML_DISCOVERY_SEEDS["notino"]
    assert "https://www.notino.fr/parfums/" in seeds
    assert all("notino.de" not in url for url in seeds)
    assert all("p-" not in url for url in seeds)


def test_notino_listing_admission_only_accepts_catalog_navigation():
    assert catalog._html_listing_url(
        "notino", "https://www.notino.fr/parfums/", "https://www.notino.fr/"
    ) == "https://www.notino.fr/parfums/"
    assert catalog._html_listing_url(
        "notino", "https://www.notino.fr/brand/fragrance/p-123456/", "https://www.notino.fr/"
    ) is None


def test_amazon_fr_and_de_have_separate_marketplace_hosts():
    assert catalog._discovery_bases("amazon_fr") == ("https://www.amazon.fr",)
    assert catalog._discovery_bases("amazon_de") == ("https://www.amazon.de",)
    assert catalog.STORE_LABELS["amazon_fr"] == "Amazon.fr"
    assert catalog.STORE_LABELS["amazon_de"] == "Amazon.de"


def test_amazon_only_admits_canonical_asin_detail_pages_for_its_market():
    fr = catalog._html_product_url(
        "amazon_fr", "https://www.amazon.fr/dp/B012345678?tag=tracking", "https://www.amazon.fr/"
    )
    de = catalog._html_product_url(
        "amazon_de", "https://www.amazon.de/gp/product/B012345678?ref=search", "https://www.amazon.de/"
    )
    assert fr == "https://www.amazon.fr/dp/B012345678"
    assert de == "https://www.amazon.de/dp/B012345678"
    assert catalog._html_product_url(
        "amazon_fr", "https://www.amazon.de/dp/B012345678", "https://www.amazon.fr/"
    ) is None
    assert catalog._html_product_url(
        "amazon_de", "https://www.amazon.de/s?k=parfum", "https://www.amazon.de/"
    ) is None
    assert catalog._html_product_url(
        "amazon_fr", "https://www.amazon.fr/product-reviews/B012345678", "https://www.amazon.fr/"
    ) is None


def test_amazon_catalog_seeds_are_locale_specific():
    fr = catalog.HTML_DISCOVERY_SEEDS["amazon_fr"]
    de = catalog.HTML_DISCOVERY_SEEDS["amazon_de"]
    assert fr and all("amazon.fr" in url for url in fr)
    assert de and all("amazon.de" in url for url in de)

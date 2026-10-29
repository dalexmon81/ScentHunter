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


def test_amazon_discovery_urls_are_market_specific():
    assert catalog._discovery_bases("amazon_fr") == ("https://www.amazon.fr",)
    assert catalog._discovery_bases("amazon_de") == ("https://www.amazon.de",)
    assert catalog._html_product_url(
        "amazon_fr", "https://www.amazon.fr/dp/B012345678?tag=tracking", "https://www.amazon.fr/"
    ) == "https://www.amazon.fr/dp/B012345678"
    assert catalog._html_product_url(
        "amazon_de", "https://www.amazon.de/gp/product/B012345678?ref=search", "https://www.amazon.de/"
    ) == "https://www.amazon.de/dp/B012345678"
    assert catalog._html_product_url(
        "amazon_fr", "https://www.amazon.de/dp/B012345678", "https://www.amazon.fr/"
    ) is None
    assert catalog._html_product_url(
        "amazon_de", "https://www.amazon.de/s?k=parfum", "https://www.amazon.de/"
    ) is None


def test_amazon_discovery_seeds_stay_in_each_marketplace():
    fr = catalog.HTML_DISCOVERY_SEEDS["amazon_fr"]
    de = catalog.HTML_DISCOVERY_SEEDS["amazon_de"]
    assert fr and all(url.startswith("https://www.amazon.fr/") for url in fr)
    assert de and all(url.startswith("https://www.amazon.de/") for url in de)


def test_failed_catalog_fetches_are_not_reported_as_verified_empty(monkeypatch):
    states = []
    monkeypatch.setattr(catalog, "_existing_count", lambda store: 0)
    monkeypatch.setattr(
        catalog,
        "_set_sync_state",
        lambda store, state, **kwargs: states.append((store, state, kwargs)),
    )

    diagnostics = {
        "visited": 2,
        "successes": 0,
        "entries": 0,
        "errors": [
            "HTTP_403;final=https://www.notino.fr/;type=text/html;bytes=5520"
        ],
    }
    status, count, detail = catalog._save_discovery(
        "notino", {}, started_at=1.0, diagnostics=diagnostics
    )

    assert status == "DISCOVERY_UNAVAILABLE"
    assert count == 0
    assert "discovery_unavailable" in detail
    assert states[0][1] == "DISCOVERY_UNAVAILABLE"


def test_successful_empty_catalog_scan_remains_empty(monkeypatch):
    states = []
    monkeypatch.setattr(catalog, "_existing_count", lambda store: 0)
    monkeypatch.setattr(
        catalog,
        "_set_sync_state",
        lambda store, state, **kwargs: states.append((store, state, kwargs)),
    )

    diagnostics = {
        "visited": 2,
        "successes": 2,
        "entries": 0,
        "errors": [],
    }
    status, count, detail = catalog._save_discovery(
        "notino", {}, started_at=1.0, diagnostics=diagnostics
    )

    assert status == "DISCOVERY_EMPTY"
    assert count == 0
    assert "no_product_urls" in detail
    assert states[0][1] == "DISCOVERY_EMPTY"


def test_first_jsonld_offer_prefers_actual_price_over_availability_only():
    from backend.catalog_engine import _first_offer

    product = {"offers": [
        {"availability": "https://schema.org/InStock"},
        {"price": "28.90", "priceCurrency": "EUR"},
    ]}
    assert _first_offer(product)["price"] == "28.90"


def test_first_jsonld_offer_keeps_availability_fallback_without_any_price():
    from backend.catalog_engine import _first_offer

    product = {"offers": [
        {"availability": "https://schema.org/OutOfStock"},
        {"availability": "https://schema.org/InStock"},
    ]}
    assert _first_offer(product)["availability"] == "https://schema.org/OutOfStock"




def test_notino_always_supplements_sitemap_with_bounded_html_discovery():
    assert catalog._should_run_html_fallback("notino", 10000, [], 1)
    assert catalog._should_run_html_fallback("notino", 0, ["sitemap unavailable"], 0)


def test_html_fallback_policy_remains_bounded_for_other_stores():
    assert catalog._should_run_html_fallback("deloox", 0, ["sitemap unavailable"], 0) is False
    assert catalog._should_run_html_fallback("amazon_fr", 10000, [], 1) is False
    assert catalog._should_run_html_fallback("sabina", 10000, [], 1) is True

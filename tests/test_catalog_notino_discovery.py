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



def test_notino_public_product_page_parser_extracts_real_offer_identity_and_variant():
    html = """<!doctype html>
    <html><head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "French Avenue Liquid Brun Eau de Parfum pour homme",
        "brand": {"@type": "Brand", "name": "French Avenue"},
        "sku": "FRV00011",
        "gtin13": "6291108730001",
        "offers": {
          "@type": "Offer",
          "price": "49.50",
          "priceCurrency": "EUR",
          "availability": "https://schema.org/InStock"
        }
      }
      </script>
    </head><body>
      <h1>French Avenue Liquid Brun Eau de Parfum pour homme</h1>
      <button>100 ml 49,50€ En stock</button>
    </body></html>""".encode("utf-8")
    item = catalog.parse_product(
        "notino",
        "https://www.notino.fr/french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/",
        html,
    )
    assert item["name"] == "French Avenue Liquid Brun Eau de Parfum pour homme"
    assert item["brand"] == "French Avenue"
    assert item["sku"] == "FRV00011"
    assert item["gtin"] == "6291108730001"
    assert item["price_num"] == 49.5
    assert item["currency"] == "EUR"
    assert item["availability"] == "in_stock"
    assert item["size_ml"] == 100
    assert item["concentration"].casefold() == "eau de parfum"


def test_amazon_marketplaces_are_inactive_until_credentials_are_available(monkeypatch):
    assert set(catalog.DISABLED_STORES) == {"amazon_de", "amazon_fr"}
    assert set(catalog.ACTIVE_STORES) == {
        "bplatz", "deloox", "easycosmetic", "notino", "orioudh",
        "parfumcity", "parfumzentrum", "perfumemarket", "sabina",
    }
    states = []
    monkeypatch.setattr(
        catalog,
        "_set_sync_state",
        lambda store, status, **kwargs: states.append((store, status, kwargs)),
    )
    result = catalog.discover_store("amazon_de")
    assert result["status"] == "DISABLED_NO_CREDENTIALS"
    assert result["count"] == 0
    assert states[0][0:2] == ("amazon_de", "DISABLED_NO_CREDENTIALS")

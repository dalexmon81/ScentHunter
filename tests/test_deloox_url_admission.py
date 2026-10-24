"""Regression tests for Deloox product URL admission."""

from types import SimpleNamespace

import backend.catalog_engine as catalog_engine
from backend.catalog_engine import _html_product_url


BASE = "https://www.deloox.nl/"


def test_deloox_localized_search_endpoints_are_not_product_urls():
    urls = (
        "https://www.deloox.nl/zoeken.html",
        "https://www.deloox.lu/chercher.html",
        "https://www.deloox.es/buscar.html",
        "https://www.deloox.com/search.html",
        "https://www.deloox.be/chercher.html",
        "https://www.deloox.com/en/search.html?page=2",
    )

    for url in urls:
        assert _html_product_url("deloox", url, BASE) is None, url


def test_deloox_canonical_numeric_product_urls_remain_admitted():
    urls = (
        (
            "https://www.deloox.com/product/1380881/chloe-le-parfum-parfum-150-ml.html",
            "https://www.deloox.com/product/1380881/chloe-le-parfum-parfum-150-ml.html",
        ),
        (
            "https://www.deloox.be/produit/1009926/hermes-eau-de-pamplemousse-rose-eau-de-cologne-100-ml.html?utm_source=test",
            "https://www.deloox.be/produit/1009926/hermes-eau-de-pamplemousse-rose-eau-de-cologne-100-ml.html",
        ),
    )

    for url, expected in urls:
        assert _html_product_url("deloox", url, BASE) == expected



def test_deloox_search_catalog_filters_navigation_urls_before_persisting(monkeypatch):
    product_url = (
        "https://www.deloox.com/product/1380881/"
        "chloe-le-parfum-parfum-150-ml.html"
    )
    fake_scraper = SimpleNamespace(
        _discover=lambda session, query: [
            "https://www.deloox.nl/zoeken.html",
            "https://www.deloox.com/search.html",
            product_url,
        ]
    )
    persisted = []

    monkeypatch.setattr(
        catalog_engine.importlib,
        "import_module",
        lambda name: fake_scraper if name == "scrapers.deloox.scraper" else None,
    )
    monkeypatch.setattr(catalog_engine, "DELOOX_GENERIC_CATALOG_QUERIES", ("parfum",))
    monkeypatch.setattr(
        catalog_engine,
        "_deloox_persist_products",
        lambda urls: persisted.extend(urls) or len(urls),
    )

    result = catalog_engine._discover_deloox_search_catalog()

    assert result["products"] == 1
    assert result["product_urls"] == {product_url: ""}
    assert persisted == [product_url]

def test_deloox_parser_accepts_accented_product_names_and_size_in_slug():
    from backend.scrapers.deloox import scraper as deloox_scraper

    cases = (
        (
            "https://www.deloox.com/product/1380881/chloe-le-parfum-parfum-150-ml.html",
            "Chloe Le Parfum",
            "Chloé Le Parfum 150 ml",
            "Chloé",
            "76.69",
            "Parfum",
        ),
        (
            "https://www.deloox.be/produit/1009926/hermes-eau-de-pamplemousse-rose-eau-de-cologne-100-ml.html",
            "Hermes Eau de Pamplemousse Rose",
            "Hermès Eau De Pamplemousse Rose Eau de Cologne 100 ml",
            "Hermès",
            "62.79",
            "Eau de Cologne",
        ),
    )

    for url, query, name, brand, price, expected_concentration in cases:
        html = f"""<!doctype html>
        <html><head><title>{name}</title>
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "{name}",
          "brand": {{"@type": "Brand", "name": "{brand}"}},
          "offers": {{"@type": "Offer", "price": "{price}", "priceCurrency": "EUR"}}
        }}
        </script></head><body><h1>{name}</h1></body></html>"""

        parsed = deloox_scraper._product(url, html, query)
        assert parsed is not None, url
        assert parsed["name"] == name
        assert parsed["source"]["source_brand"] == brand
        assert parsed["price"] == f"{price.replace('.', ',')} €"
        assert parsed["attributes"]["concentration"]["value"] == expected_concentration

        # Exercise the exact catalog-refresh adapter with already-fetched bytes.
        # It must decode the response and preserve accent-insensitive matching
        # without performing a second HTTP request.
        parsed_refresh = deloox_scraper.extract_product_page(
            session=None,
            url=url,
            query="ignored-by-exact-url-refresh",
            html=html.encode("utf-8"),
        )
        assert parsed_refresh is not None, url
        assert parsed_refresh["name"] == name
        assert parsed_refresh["source"]["source_brand"] == brand
        assert parsed_refresh["offer"]["price"] == float(price)
        assert parsed_refresh["attributes"]["concentration"]["value"] == expected_concentration

def test_deloox_url_admission_rejects_localized_home_redirect_targets():
    # Search/category URLs can return HTTP 200 after redirecting to the
    # localized homepage. URL admission must be based on path shape, not status.
    urls = (
        "https://www.deloox.nl/",
        "https://www.deloox.lu/",
        "https://www.deloox.es/",
        "https://www.deloox.com/",
        "https://www.deloox.be/",
    )
    for url in urls:
        assert _html_product_url("deloox", url, BASE) is None, url


def test_deloox_url_admission_keeps_numeric_product_routes_across_locales():
    urls = (
        "https://www.deloox.nl/product/12345/example-product-eau-de-parfum-50-ml.html",
        "https://www.deloox.lu/produit/12345/example-product-eau-de-parfum-50-ml.html",
        "https://www.deloox.es/producto/12345/example-product-eau-de-parfum-50-ml.html",
        "https://www.deloox.com/product/12345/example-product-eau-de-parfum-50-ml.html",
    )
    for url in urls:
        assert _html_product_url("deloox", url, BASE) == url, url

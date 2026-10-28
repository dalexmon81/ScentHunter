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


def test_deloox_localized_category_pages_are_not_admitted_as_products():
    urls = (
        "https://www.deloox.lu/de/kategorie/1000265/joop-damendufte.html",
        "https://www.deloox.lu/fr/categorie/1000265/joop-parfums.html",
        "https://www.deloox.nl/categorie/1000265/joop-parfum.html",
        "https://www.deloox.es/categoria/1000265/joop-perfumes.html",
        "https://www.deloox.com/en/category/1000265/joop-perfumes.html",
    )

    for url in urls:
        assert _html_product_url("deloox", url, BASE) is None, url
        assert catalog_engine._coverage_allowed_url("deloox", url) == "", url


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


def test_coverage_admission_rejects_deloox_navigation_but_keeps_products():
    assert catalog_engine._coverage_allowed_url(
        "deloox", "https://www.deloox.nl/zoeken.html"
    ) == ""
    assert catalog_engine._coverage_allowed_url(
        "deloox", "https://www.deloox.com/en/search.html?page=2"
    ) == ""
    assert catalog_engine._coverage_allowed_url(
        "deloox", "https://www.deloox.com/"
    ) == ""
    product = (
        "https://www.deloox.com/product/1380881/"
        "chloe-le-parfum-parfum-150-ml.html?utm_source=test"
    )
    assert catalog_engine._coverage_allowed_url("deloox", product) == (
        "https://www.deloox.com/product/1380881/"
        "chloe-le-parfum-parfum-150-ml.html"
    )


def test_refresh_url_rejects_deloox_search_url_before_network(monkeypatch):
    calls = []

    def unexpected_http_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("non-product URL must be rejected before HTTP")

    monkeypatch.setattr(catalog_engine, "http_get", unexpected_http_get)
    result = catalog_engine.refresh_url("deloox", "https://www.deloox.nl/zoeken.html")
    assert result is None
    assert calls == []


def test_deloox_visible_out_of_stock_overrides_stale_jsonld_offer():
    from backend.scrapers.deloox import scraper as deloox_scraper

    url = (
        "https://www.deloox.be/produit/1385920/"
        "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
    )
    name = "French Avenue Liquid Brun Extrait de Parfum Limited edition 150 ml"
    html = f"""<!doctype html>
    <html><head>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "{name}",
      "brand": {{"@type": "Brand", "name": "French Avenue"}},
      "sku": "1385920",
      "gtin14": "6298042001831",
      "offers": {{
        "@type": "Offer",
        "price": "39.89",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock"
      }}
    }}
    </script></head>
    <body>
      <h1>French Avenue Liquid Brun Extrait de Parfum Limited edition</h1>
      <div class="availability">Niet op voorraad</div>
    </body></html>"""

    parsed = deloox_scraper._product(
        url, html, "Liquid Brun Limited Edition 150 ml"
    )

    assert parsed is not None
    assert parsed["attributes"]["size_ml"]["value"] == 150
    assert parsed["identity"]["gtin"]["value"] == "6298042001831"
    assert parsed["offer"]["availability"] == "out_of_stock"
    assert parsed["offer"]["price"] is None
    assert parsed["price"] is None


def test_deloox_parser_preserves_gtin14_for_limited_edition_150ml():
    from backend.scrapers.deloox import scraper as deloox_scraper

    url = (
        "https://www.deloox.be/produit/1385920/"
        "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
    )
    name = "French Avenue Liquid Brun Extrait de Parfum Limited edition 150 ml"
    html = f"""<!doctype html>
    <html><head>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "{name}",
      "brand": {{"@type": "Brand", "name": "French Avenue"}},
      "sku": "1385920",
      "gtin14": "6298042001831",
      "offers": {{
        "@type": "Offer",
        "price": "39.89",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock"
      }}
    }}
    </script></head><body><h1>{name}</h1></body></html>"""

    parsed = deloox_scraper._product(
        url, html, "Liquid Brun Limited Edition 150 ml"
    )

    assert parsed is not None
    assert parsed["identity"]["gtin"] == {
        "value": "6298042001831",
        "source": "jsonld",
    }
    assert parsed["identity"]["sku"]["value"] == "1385920"
    assert parsed["attributes"]["size_ml"]["value"] == 150
    assert parsed["attributes"]["concentration"]["value"] == "Extrait de Parfum"

    # catalog_engine.refresh_url() persists these flat fields. Returning only
    # the nested schema silently stored this live in-stock offer as an empty,
    # out-of-stock row with no GTIN or price.
    assert parsed["brand"] == "French Avenue"
    assert parsed["gtin"] == "6298042001831"
    assert parsed["sku"] == "1385920"
    assert parsed["size_ml"] == 150
    assert parsed["concentration"] == "Extrait de Parfum"
    assert parsed["price_num"] == 39.89
    assert parsed["currency"] == "EUR"
    assert parsed["availability"] == "in_stock"

    # The diagnostic must pass the parser's verified identity to the matcher;
    # this exact GTIN maps only to the Limited Edition 150 ml variant.
    from pathlib import Path
    from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
    from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from backend.scenthunter_next_engine.offer_normalizer import normalize_offer

    offer = normalize_offer(
        {
            "name": parsed["name"],
            "brand": parsed["brand"],
            "size_ml": parsed["size_ml"],
            "price": parsed["price_num"],
            "availability": parsed["availability"],
            "url": parsed["url"],
            "identity": parsed["identity"],
        },
        retailer="deloox",
    )
    catalog_path = Path(catalog_engine.__file__).resolve().parent / "product_catalog.json"
    match = CanonicalMatcher(CatalogRepository.from_file(catalog_path)).match(offer)
    assert match.status.value == "matched"
    assert match.canonical_product_id == "SH-0031"
    assert match.canonical_variant_id == "VAR-f5aff76b4bb5de8a"
    assert match.reason == "verified_gtin_exact_variant"

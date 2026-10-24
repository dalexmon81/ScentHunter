"""Regression tests for Deloox product URL admission."""

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

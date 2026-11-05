from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from scrapers.bplatz.scraper import parse_product_html

FIXTURE = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
META = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json"
QUERY = "French Avenue Liquid Brun"


def _fixture_product():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                typ = item.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if any(str(value).lower() == "product" for value in types):
                    return item
                if isinstance(item.get("@graph"), list):
                    queue.extend(item["@graph"])
    raise AssertionError("Authentic Bplatz fixture has no Product JSON-LD")


def _parse(*, name=None, price="39.90", currency="EUR", availability="https://schema.org/InStock"):
    product = _fixture_product()
    product["name"] = name or product["name"]
    product["offers"] = {
        "price": price,
        "priceCurrency": currency,
        "availability": availability,
        "url": json.loads(META.read_text(encoding="utf-8"))["url_final"],
    }
    html = (
        '<html><body><h1>' + product["name"] + '</h1>'
        '<script type="application/ld+json">'
        + json.dumps(product, ensure_ascii=False)
        + '</script></body></html>'
    )
    return parse_product_html(
        html,
        json.loads(META.read_text(encoding="utf-8"))["url_final"],
        QUERY,
    )


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        ("https://schema.org/InStock", "in_stock"),
        ("https://schema.org/OutOfStock", "out_of_stock"),
        ("https://schema.org/PreOrder", "unknown"),
        ("", "unknown"),
    ],
)
def test_stock_signal_matrix_is_conservative(signal, expected):
    parsed = _parse(availability=signal)
    assert parsed is not None
    assert parsed["availability"] == expected
    assert parsed["available"] is (
        True if expected == "in_stock" else False if expected == "out_of_stock" else None
    )


@pytest.mark.parametrize("price", [None, "", "0", "0.00", "-12.50", "-1", "not-a-price"])
def test_invalid_price_matrix_never_produces_positive_price(price):
    parsed = _parse(price=price)
    assert parsed is not None
    assert parsed["price_num"] is None
    assert parsed["price"] is None


@pytest.mark.parametrize(
    ("currency", "price_expected"),
    [("EUR", 39.90), ("USD", None), ("GBP", None)],
)
def test_currency_matrix_never_relabels_foreign_amount_as_eur(currency, price_expected):
    parsed = _parse(currency=currency)
    assert parsed is not None
    if price_expected is None:
        assert parsed["price_num"] is None
    else:
        assert parsed["price_num"] == pytest.approx(price_expected)
    assert parsed["offer"]["currency"] == "EUR"


@pytest.mark.parametrize(
    ("name", "expected_size", "expected_concentration"),
    [
        ("French Avenue Liquid Brun Eau de Parfum 100ml", 100, "Eau de Parfum"),
        ("French Avenue Liquid Brun Eau de Toilette 100ml", 100, "Eau de Toilette"),
        ("French Avenue Liquid Brun Extrait de Parfum 100ml", 100, "Extrait de Parfum"),
        ("French Avenue Liquid Brun Eau de Parfum 150ml", 150, "Eau de Parfum"),
    ],
)
def test_size_and_concentration_are_parsed_from_product_identity(name, expected_size, expected_concentration):
    parsed = _parse(name=name)
    assert parsed is not None
    assert parsed["size_ml"] == expected_size
    assert parsed["concentration"] == expected_concentration


def test_missing_sku_and_gtin_remain_missing():
    product = _fixture_product()
    product.pop("sku", None)
    product.pop("gtin13", None)
    product.pop("gtin", None)
    product["offers"] = {
        "price": "39.90",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock",
    }
    html = (
        '<html><body><h1>' + product["name"] + '</h1>'
        '<script type="application/ld+json">'
        + json.dumps(product, ensure_ascii=False)
        + '</script></body></html>'
    )
    parsed = parse_product_html(html, "https://en.bplatz.de/products/liquid-brun", QUERY)
    assert parsed is not None
    assert parsed["sku"] is None
    assert parsed["gtin"] is None
    assert parsed["identity"]["sku"] is None
    assert parsed["identity"]["gtin"] is None

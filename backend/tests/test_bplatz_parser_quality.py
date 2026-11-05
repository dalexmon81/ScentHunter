import json

import pytest

from scrapers.bplatz import scraper


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("89.90", 89.90),
        ("89,90 €", 89.90),
        ("1.299,00 EUR", 1299.00),
        ("0", None),
        ("0.00", None),
        ("-1.00", None),
        ("-89,90 EUR", None),
        ("not a price", None),
        ("10000.00", None),
    ],
)
def test_bplatz_price_parser_rejects_invalid_or_non_positive_values(raw, expected):
    assert scraper.parse_price(raw) == expected


@pytest.mark.parametrize(
    ("title", "expected_size", "expected_concentration"),
    [
        ("Dior Sauvage Eau de Parfum 100 ml", 100, "Eau de Parfum"),
        ("Dior Sauvage Eau de Toilette 60 ml", 60, "Eau de Toilette"),
        ("Dior Sauvage Parfum 200 ml", 200, "Parfum"),
        ("Dior Sauvage Extrait de Parfum 75 ml", 75, "Extrait de Parfum"),
        ("Dior Sauvage Eau de Parfum 10 cl", 100, "Eau de Parfum"),
        ("Dior Sauvage Eau de Parfum", None, "Eau de Parfum"),
    ],
)
def test_bplatz_extracts_size_and_concentration_without_guessing(
    title, expected_size, expected_concentration
):
    assert scraper.size_ml(title) == expected_size
    assert scraper.concentration(title) == expected_concentration


def _product_html(*, title, price, availability):
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": title,
        "brand": {"@type": "Brand", "name": "Dior"},
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": "EUR",
            "availability": f"https://schema.org/{availability}",
        },
    }
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(product)
        + "</script></head><body><h1>"
        + title
        + "</h1></body></html>"
    )


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        ("InStock", "in_stock"),
        ("OutOfStock", "out_of_stock"),
        ("PreOrder", "unknown"),
    ],
)
def test_bplatz_jsonld_availability_is_conservative(availability, expected):
    title = "Dior Sauvage Eau de Parfum 100 ml"
    row = scraper.parse_product_html(
        _product_html(title=title, price="89.90", availability=availability),
        "https://en.bplatz.de/products/dior-sauvage",
        "Dior Sauvage",
    )
    assert row is not None
    assert row["availability"] == expected
    assert row["size_ml"] == 100
    assert row["concentration"] == "Eau de Parfum"


def test_bplatz_wrong_size_is_not_rewritten_to_requested_size():
    title = "Dior Sauvage Eau de Parfum 60 ml"
    row = scraper.parse_product_html(
        _product_html(title=title, price="89.90", availability="InStock"),
        "https://en.bplatz.de/products/dior-sauvage-60",
        "Dior Sauvage",
    )
    assert row is not None
    assert row["size_ml"] == 60
    assert row["concentration"] == "Eau de Parfum"


@pytest.mark.parametrize("price", ["0", "0.00", "-12.50", "10000.00"])
def test_bplatz_invalid_price_is_not_parsed_as_a_purchasable_price(price):
    title = "Dior Sauvage Eau de Parfum 100 ml"
    row = scraper.parse_product_html(
        _product_html(title=title, price=price, availability="InStock"),
        "https://en.bplatz.de/products/dior-sauvage",
        "Dior Sauvage",
    )
    assert row is not None
    assert row["price_num"] is None

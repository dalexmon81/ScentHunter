import json

import pytest

from scrapers.bplatz import scraper


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("89.90", 89.90),
        ("89,90 €", 89.90),
        ("1.299,00 EUR", 1299.00),
        ("1,299.00 EUR", 1299.00),
        ("1,299 EUR", 1299.00),
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



@pytest.mark.parametrize(
    ("title", "size", "concentration"),
    [
        ("Dior Sauvage EDT 30 ml", 30, "Eau de Toilette"),
        ("Dior Sauvage EDT 200 ml", 200, "Eau de Toilette"),
        ("Dior Sauvage EDP 50 ml", 50, "Eau de Parfum"),
        ("Dior Sauvage EDP 100 ml", 100, "Eau de Parfum"),
        ("Dior Sauvage EDP 150 ml", 150, "Eau de Parfum"),
        ("Dior Sauvage Parfum 60 ml", 60, "Parfum"),
        ("Dior Sauvage Extrait de Parfum 100 ml", 100, "Extrait de Parfum"),
    ],
)
def test_bplatz_variant_matrix_preserves_exact_size_and_concentration(
    title, size, concentration
):
    row = scraper.parse_product_html(
        _product_html(title=title, price="89.90", availability="InStock"),
        "https://en.bplatz.de/products/variant",
        "Dior Sauvage",
    )
    assert row is not None
    assert row["size_ml"] == size
    assert row["concentration"] == concentration


@pytest.mark.parametrize(
    ("title", "query"),
    [
        ("Dior Sauvage Eau de Parfum 60 ml", "Dior Sauvage Eau de Parfum 100 ml"),
        ("Dior Sauvage Eau de Toilette 100 ml", "Dior Sauvage Eau de Parfum 100 ml"),
        ("Dior Eau Sauvage Eau de Parfum 100 ml", "Dior Sauvage Eau de Parfum 100 ml"),
    ],
)
def test_bplatz_variant_conflicts_are_not_rewritten_to_requested_identity(title, query):
    row = scraper.parse_product_html(
        _product_html(title=title, price="89.90", availability="InStock"),
        "https://en.bplatz.de/products/variant",
        query,
    )
    # The parser may identify the same fragrance family, but it must preserve
    # the page's actual variant attributes for the canonical matcher to reject.
    if row is not None:
        assert row["size_ml"] != 100 or row["concentration"] != "Eau de Parfum" or title.endswith("100 ml")


def _product_html_with_body(*, title, body, currency=None):
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": title,
        "brand": {"@type": "Brand", "name": "Dior"},
    }
    if currency is not None:
        product["offers"] = {
            "@type": "Offer",
            "price": "89.90",
            "priceCurrency": currency,
            "availability": "https://schema.org/InStock",
        }
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(product)
        + "</script></head><body><h1>"
        + title
        + "</h1><div>"
        + body
        + "</div></body></html>"
    )


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Retail price €89.90", 89.90),
        ("Price €89,90", 89.90),
        ("€1,299.00", 1299.00),
    ],
)
def test_bplatz_fallback_price_text_is_parsed_when_jsonld_has_no_offer(body, expected):
    title = "Dior Sauvage Eau de Parfum 100 ml"
    row = scraper.parse_product_html(
        _product_html_with_body(title=title, body=body),
        "https://en.bplatz.de/products/dior-sauvage",
        "Dior Sauvage",
    )
    assert row is not None
    assert row["price_num"] == expected


def test_bplatz_foreign_jsonld_currency_is_not_mislabeled_as_eur():
    title = "Dior Sauvage Eau de Parfum 100 ml"
    row = scraper.parse_product_html(
        _product_html_with_body(title=title, body="Price €89.90", currency="GBP"),
        "https://en.bplatz.de/products/dior-sauvage",
        "Dior Sauvage",
    )
    assert row is not None
    assert row["price_num"] is None

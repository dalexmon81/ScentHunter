"""Offline offer-contract regressions for ParfumCity and Sabina."""
import json

from scrapers.parfumcity import scraper as parfumcity
from scrapers.sabina import scraper as sabina


def test_parfumcity_shopify_variant_keeps_variant_identity_and_unknown_currency():
    product = {
        "id": 9001,
        "title": "French Avenue Liquid Brun Eau de Parfum",
        "vendor": "French Avenue",
        "variants": [],
    }
    variant = {
        "id": 9002,
        "title": "100 ml",
        "sku": "FA-LB-100",
        "barcode": "6290360599999",
        "price": "31.85",
        "available": True,
    }

    row = parfumcity.make_item(
        product, variant,
        "https://www.parfumcity.nl/products/liquid-brun",
        "Liquid Brun",
    )

    assert row["identity"]["store_product_id"]["value"] == 9001
    assert row["identity"]["store_variant_id"]["value"] == 9002
    assert row["identity"]["gtin"]["value"] == "6290360599999"
    assert row["attributes"]["size_ml"]["value"] == 100
    assert row["offer"] == {
        "price": 31.85,
        "currency": None,
        "availability": "in_stock",
    }


def test_parfumcity_unknown_variant_stock_is_not_out_of_stock():
    row = parfumcity.make_item(
        {"id": 1, "title": "Liquid Brun", "vendor": "French Avenue"},
        {"id": 2, "title": "100 ml", "price": "31.85"},
        "https://www.parfumcity.nl/products/liquid-brun",
        "Liquid Brun",
    )
    assert row["offer"]["availability"] == "unknown"
    assert row["available"] is None


def test_sabina_product_page_does_not_invent_currency_or_stock():
    url = "https://www.sabina.com/es/perfumes/123-liquid-brun.html"
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
        "brand": {"@type": "Brand", "name": "French Avenue"},
        "sku": "FA-LB-100",
        "gtin13": "6290360599999",
        "offers": {
            "@type": "Offer",
            "url": url,
            "price": "31.85",
        },
    }
    html = (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(payload)
        + "</script></head><body><h1>"
        + payload["name"]
        + "</h1></body></html>"
    )

    row = sabina.extract_product_page(
        None, url, "Liquid Brun", html=html
    )

    assert row is not None
    assert row["identity"]["gtin"]["value"] == "6290360599999"
    assert row["offer"]["price"] == 31.85
    assert row["offer"]["currency"] is None
    assert row["offer"]["availability"] == "unknown"
    assert row["available"] is None


def test_sabina_structured_offer_keeps_explicit_currency_and_stock():
    url = "https://www.sabina.com/es/perfumes/123-liquid-brun.html"
    payload = {
        "@type": "Product",
        "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
        "offers": {
            "@type": "Offer",
            "url": url,
            "price": "31.85",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        },
    }
    html = (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(payload)
        + "</script></head><body><h1>"
        + payload["name"]
        + "</h1></body></html>"
    )
    row = sabina.extract_product_page(None, url, "Liquid Brun", html=html)
    assert row["offer"]["currency"] == "EUR"
    assert row["offer"]["availability"] == "in_stock"

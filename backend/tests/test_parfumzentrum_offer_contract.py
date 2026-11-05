"""Offline offer-contract tests for the ParfumZentrum adapter."""
import json

from scrapers.parfumzentrum import scraper


URL = "https://www.parfum-zentrum.de/berdoues-monoi-tiare-eau-de-toilette-100-ml-unisex_z904294/"


def _page(offer):
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Berdoues Monoi & Tiare Eau de Toilette 100 ml",
        "brand": {"@type": "Brand", "name": "Berdoues"},
        "sku": "pz-904294",
        "gtin13": "3610400034567",
        "offers": {"@type": "Offer", "url": URL, **offer},
    }
    return (
        "<html><head><script type='application/ld+json'>"
        + json.dumps(product)
        + "</script></head><body><h1>"
        + product["name"]
        + "</h1></body></html>"
    )


def test_parfumzentrum_preserves_explicit_iso_currency_and_offer_identity():
    row = scraper.extract_product_page(
        None,
        URL,
        html=_page({
            "price": "29.40",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        }),
    )

    assert row is not None
    assert row["identity"]["gtin"]["value"] == "3610400034567"
    assert row["identity"]["sku"]["value"] == "pz-904294"
    assert row["attributes"]["size_ml"]["value"] == 100
    assert row["offer"] == {
        "price": 29.4,
        "currency": "EUR",
        "availability": "in_stock",
    }


def test_parfumzentrum_does_not_infer_currency_when_jsonld_omits_it():
    row = scraper.extract_product_page(
        None,
        URL,
        html=_page({
            "price": "29.40",
            "availability": "https://schema.org/InStock",
        }),
    )

    assert row is not None
    assert row["offer"]["price"] == 29.4
    assert row["offer"]["currency"] is None
    assert row["offer"]["availability"] == "in_stock"


def test_parfumzentrum_rejects_malformed_currency_instead_of_publishing_it():
    row = scraper.extract_product_page(
        None,
        URL,
        html=_page({
            "price": "29.40",
            "priceCurrency": "EURO",
            "availability": "https://schema.org/InStock",
        }),
    )

    assert row is not None
    assert row["offer"]["currency"] is None


def test_parfumzentrum_keeps_explicit_out_of_stock_without_a_price():
    row = scraper.extract_product_page(
        None,
        URL,
        html=_page({
            "availability": "https://schema.org/OutOfStock",
        }),
    )

    assert row is not None
    assert row["offer"]["price"] is None
    assert row["offer"]["availability"] == "out_of_stock"
    assert row["available"] is False


def test_parfumzentrum_rejects_product_urls_outside_the_retailer_domain():
    row = scraper.extract_product_page(
        None,
        "https://example.com/berdoues-monoi-tiare_z904294/",
        html=_page({
            "price": "29.40",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        }),
    )

    assert row is None

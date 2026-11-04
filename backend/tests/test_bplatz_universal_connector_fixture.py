from pathlib import Path

import pytest

from app.connectors import BplatzConnector
from scrapers.bplatz import scraper


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "connectors"
    / "bplatz-dior-sauvage-edp-100.html"
)
URL = "https://en.bplatz.de/products/dior-sauvage-eau-de-parfum"


def parsed_fixture():
    html = FIXTURE.read_text(encoding="utf-8")
    return scraper.parse_product_html(html, URL, "Dior Sauvage")


def test_saved_bplatz_jsonld_fixture_extracts_exact_offer_evidence():
    row = parsed_fixture()
    assert row is not None
    assert row["brand"] == "Dior"
    assert row["name"] == "Dior Sauvage Eau de Parfum 100 ml"
    assert row["sku"] == "BPL-DIOR-SAU-EDP-100"
    assert row["gtin"] is None  # No verified GTIN in this saved fixture.
    assert row["size_ml"] == 100
    assert row["concentration"] == "Eau de Parfum"
    assert row["price_num"] == 89.90
    assert row["availability"] == "in_stock"
    assert row["url"] == URL


def test_bplatz_connector_maps_saved_fixture_to_universal_offer():
    connector = BplatzConnector()
    row = parsed_fixture()
    offers = connector.parse_raw(row)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.store == "bplatz"
    assert offer.external_product_id == "BPL-DIOR-SAU-EDP-100"
    assert offer.gtin is None
    assert offer.brand == "Dior"
    assert offer.fragrance == "sauvage"
    assert offer.concentration == "edp"
    assert offer.size_ml == 100
    assert str(offer.price) == "89.9"
    assert offer.currency == "EUR"
    assert offer.availability == "in_stock"
    assert connector.validate_offer(offer)[0]


def test_bplatz_does_not_fabricate_missing_sku_or_gtin():
    row = parsed_fixture()
    row["sku"] = None
    row["gtin"] = None
    row["identity"]["sku"] = None
    row["identity"]["gtin"] = None

    offer = BplatzConnector().parse_raw(row)[0]
    assert offer.gtin is None
    # The connector contract falls back to the product URL as external identity;
    # it must not mislabel that URL as an SKU or GTIN.
    assert offer.external_product_id == URL


@pytest.mark.parametrize(
    ("page_text", "expected"),
    [
        ("Product unavailable", "out_of_stock"),
        ("Available soon — currently out of stock", "out_of_stock"),
        ("Add to cart — In stock", "in_stock"),
        ("See product details", "unknown"),
    ],
)
def test_bplatz_stock_signals_are_conservative(page_text, expected):
    assert scraper.availability_from_text(page_text) == expected


def test_bplatz_parser_rejects_wrong_product_query():
    html = FIXTURE.read_text(encoding="utf-8")
    assert scraper.parse_product_html(html, URL, "Chanel No 5") is None

# CI coverage: this fixture-only suite is included in the Phase 4 connector contract workflow.

"""Regression gate from captured live Parfum-Zentrum parser output to conservative canonical matching.

The live page is not fetched by this unit test. Its observed output is captured
here so CI is deterministic; the separate live-probe workflow verifies the
current retailer response. No database access or catalog mutation occurs.
"""
from pathlib import Path

from backend.scenthunter_next_engine.models import MatchStatus
from backend.scenthunter_next_engine.next_engine_service import NextEngineService

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "backend" / "product_catalog.json"


def test_live_profondo_125ml_edp_resolves_by_verified_gtin_variant_evidence():
    service = NextEngineService.from_catalog_file(CATALOG)
    result = service.process_records(
        [{
            "name": "Giorgio Armani Acqua di Giò Profondo Eau De Parfum 125 ml (man)",
            "brand": "Giorgio Armani",
            "size_ml": 125,
            "price": 95.44,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-125-ml-man_z771966/",
            "gtin": "3614272865235",
            "sku": "771966",
        }],
        retailer="ParfumZentrum",
    )

    assert result.rejected_rows == ()
    assert result.normalized_offer_count == 1
    assert result.matched_offer_count == 1
    assert result.unresolved == ()
    assert result.ambiguous == ()
    group = result.groups[0]
    assert group.canonical_product_id == "SH-0043"
    assert group.canonical_variant_id == "VAR-09a73d0a5594cf49"
    assert group.offers[0].raw_payload["gtin"] == "3614272865235"


def test_verified_gtin_with_conflicting_size_fails_closed():
    service = NextEngineService.from_catalog_file(CATALOG)
    result = service.process_records(
        [{
            "name": "Giorgio Armani Acqua di Giò Profondo Eau De Parfum 100 ml (man)",
            "brand": "Giorgio Armani",
            "size_ml": 100,
            "price": 95.44,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://www.parfum-zentrum.de/example",
            "gtin": "3614272865235",
            "sku": "conflicting-size",
        }],
        retailer="ParfumZentrum",
    )

    assert result.matched_offer_count == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "verified_gtin_size_conflict"
    assert result.ambiguous == ()


def test_live_profondo_refillable_100ml_bottle_maps_to_regular_edp_variant():
    service = NextEngineService.from_catalog_file(CATALOG)
    result = service.process_records(
        [{
            "name": "Giorgio Armani Acqua di Giò Profondo Eau De Parfum - nachfüllbar 100 ml (man)",
            "brand": "Giorgio Armani",
            "size_ml": 100,
            "price": 83.95,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-nachfullbar-100-ml-man_z947818/",
            "gtin": "3614273953849",
            "sku": "947818",
        }],
        retailer="ParfumZentrum",
    )

    assert result.rejected_rows == ()
    assert result.normalized_offer_count == 1
    assert result.matched_offer_count == 1
    assert result.unresolved == ()
    assert result.ambiguous == ()
    assert result.groups[0].canonical_product_id == "SH-AUTO-0019"
    assert result.groups[0].canonical_variant_id == "VAR-46b03c1f1cff0a6e"


def test_profondo_refill_pack_does_not_map_to_refillable_100ml_bottle():
    service = NextEngineService.from_catalog_file(CATALOG)
    result = service.process_records(
        [{
            "name": "Giorgio Armani Acqua di Gio Profondo Eau de Parfum Refill 100 ml",
            "brand": "Giorgio Armani",
            "size_ml": 100,
            "price": 83.95,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://example.invalid/profondo-refill-pack",
            "gtin": "3614273953849",
        }],
        retailer="test",
    )

    assert result.matched_offer_count == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "verified_gtin_packaging_conflict"



def test_profondo_75ml_edp_resolves_by_verified_gtin_variant_evidence():
    service = NextEngineService.from_catalog_file(CATALOG)
    result = service.process_records(
        [{
            "name": "Giorgio Armani Acqua di Giò Profondo Eau de Parfum 75 ml",
            "brand": "Giorgio Armani",
            "size_ml": 75,
            "price": 100.90,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://www.ladyparfum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-75-ml-herren-3975-en",
            "gtin": "3614272865228",
            "sku": "op107",
        }],
        retailer="LadyParfum",
    )

    assert result.rejected_rows == ()
    assert result.normalized_offer_count == 1
    assert result.matched_offer_count == 1
    assert result.unresolved == ()
    assert result.ambiguous == ()
    assert result.groups[0].canonical_product_id == "SH-0043"
    assert result.groups[0].canonical_variant_id == "VAR-89c2a2a86bedb3c5"


def test_profondo_75ml_gtin_with_125ml_size_fails_closed():
    service = NextEngineService.from_catalog_file(CATALOG)
    result = service.process_records(
        [{
            "name": "Giorgio Armani Acqua di Giò Profondo Eau de Parfum 125 ml",
            "brand": "Giorgio Armani",
            "size_ml": 125,
            "price": 100.90,
            "currency": "EUR",
            "availability": "in_stock",
            "url": "https://example.invalid/profondo",
            "gtin": "3614272865228",
        }],
        retailer="test",
    )

    assert result.matched_offer_count == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "verified_gtin_size_conflict"
    assert result.ambiguous == ()

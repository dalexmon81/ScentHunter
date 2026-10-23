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


def test_live_profondo_125ml_edp_surfaces_duplicate_identity_as_ambiguous():
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
    # The live title now resolves to the known duplicate identity family, but
    # both canonical products share the same name. Do not silently choose by
    # size alone; GTIN-to-variant evidence must be represented in the catalog
    # before this offer can be assigned automatically.
    assert result.matched_offer_count == 0
    assert result.groups == ()
    assert result.unresolved == ()
    assert len(result.ambiguous) == 1
    assert set(result.ambiguous[0].candidate_product_ids) == {"SH-0043", "SH-AUTO-0019"}


def test_live_profondo_refill_does_not_map_to_regular_100ml_edp():
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
    assert result.matched_offer_count == 0
    assert len(result.unresolved) + len(result.ambiguous) == 1
    assert all(
        group.canonical_variant_id != "VAR-46b03c1f1cff0a6e"
        for group in result.groups
    )

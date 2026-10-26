"""Contract tests for the next-engine integration boundary.

These tests do not integrate the new engine into production. They establish the
explicit contract that a future adapter must satisfy before any activation.
"""
from pathlib import Path

import pytest

from backend.scenthunter_next_engine.next_engine_service import NextEngineService


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "backend" / "product_catalog.json"


@pytest.fixture()
def service():
    return NextEngineService.from_catalog_file(CATALOG)


def test_empty_batch_returns_empty_auditable_result(service):
    result = service.process_records([], retailer="integration-contract-test")

    assert result.normalized_offer_count == 0
    assert result.matched_offer_count == 0
    assert result.groups == ()
    assert result.unresolved == ()
    assert result.ambiguous == ()
    assert result.rejected_rows == ()


def test_invalid_rows_are_reported_not_silently_dropped(service):
    result = service.process_records(
        [
            {"brand": "Missing name", "price": "10.00"},
            {"name": "Valid-looking unknown fragrance", "brand": "Unknown Brand",
             "price": "12.00"},
        ],
        retailer="integration-contract-test",
    )

    assert result.normalized_offer_count == 1
    assert result.matched_offer_count == 0
    assert len(result.rejected_rows) == 1
    assert result.rejected_rows[0]["index"] == 0
    assert result.rejected_rows[0]["reason"]
    assert len(result.unresolved) == 1


def test_service_does_not_mutate_input_records_or_catalog(service):
    catalog_before = service.catalog.all_products()
    records = [
        {
            "name": "Definitely Unknown Integration Contract Fragrance",
            "brand": "Definitely Unknown Integration Contract Brand",
            "price": "17.50",
            "url": "https://integration-contract.example/item",
        }
    ]
    records_before = [dict(item) for item in records]

    service.process_records(records, retailer="integration-contract-test")

    assert records == records_before
    assert service.catalog.all_products() == catalog_before


def test_missing_retailer_fails_closed(service):
    with pytest.raises(TypeError):
        service.process_records([])


def test_unknown_offer_never_receives_invented_canonical_ids(service):
    result = service.process_records(
        [
            {
                "name": "Definitely Unknown Integration Contract Fragrance",
                "brand": "Definitely Unknown Integration Contract Brand",
                "price": "17.50",
            }
        ],
        retailer="integration-contract-test",
    )

    assert result.matched_offer_count == 0
    assert len(result.unresolved) == 1
    assert result.unresolved[0].canonical_product_id is None
    assert result.unresolved[0].canonical_variant_id is None

"""Integration-style tests for the isolated next-engine service."""
from decimal import Decimal
from pathlib import Path

from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.scenthunter_next_engine.models import CanonicalProduct, CanonicalVariant, MatchStatus, RetailerOffer
from backend.scenthunter_next_engine.next_engine_service import NextEngineService


def make_service() -> NextEngineService:
    catalog = CatalogRepository(
        products=(
            CanonicalProduct(
                product_id="product-example",
                brand="Example",
                name="Example Fragrance",
                variants=(
                    CanonicalVariant(variant_id="variant-example-100", size_ml=100),
                    CanonicalVariant(variant_id="variant-example-50", size_ml=50),
                ),
                canonical_image_url="https://catalog.example/image.jpg",
            ),
        ),
        source=Path("test-catalog.json"),
    )
    return NextEngineService(catalog)


def test_process_records_normalizes_matches_and_aggregates():
    service = make_service()
    records = [
        {
            "name": "Example Fragrance",
            "brand": "Example",
            "size_ml": 100,
            "price": "49.90",
            "url": "https://shop.example/product",
        },
        {
            "title": "Example Fragrance",
            "brand_name": "Example",
            "volume_ml": 100,
            "current_price": 54.5,
            "product_url": "https://other-shop.example/product",
        },
    ]

    result = service.process_records(records, retailer="test-shop")

    assert result.normalized_offer_count == 2
    assert result.matched_offer_count == 2
    assert result.rejected_rows == ()
    assert len(result.groups) == 1
    assert result.groups[0].canonical_product_id == "product-example"
    assert result.groups[0].canonical_variant_id == "variant-example-100"
    assert len(result.groups[0].offers) == 2


def test_process_records_keeps_missing_format_unresolved():
    service = make_service()
    result = service.process_records(
        [{"name": "Example Fragrance", "brand": "Example", "price": 49.9}],
        retailer="test-shop",
    )

    assert result.matched_offer_count == 0
    assert result.groups == ()
    assert len(result.unresolved) == 1
    assert result.unresolved[0].status is MatchStatus.UNRESOLVED
    assert result.unresolved[0].reason == "format_missing_for_multi_variant_product"


def test_process_records_separates_rejected_rows_from_unresolved_offers():
    service = make_service()
    result = service.process_records(
        [
            {"brand": "Example", "size_ml": 100, "price": 49.9},
            {"name": "Unlisted Fragrance", "brand": "Example", "size_ml": 100},
        ],
        retailer="test-shop",
    )

    assert len(result.rejected_rows) == 1
    assert result.rejected_rows[0]["index"] == 0
    assert "product-name field" in result.rejected_rows[0]["reason"]
    assert len(result.unresolved) == 1
    assert result.unresolved[0].reason == "no_exact_canonical_name_and_brand_match"
    assert result.aggregation.input_count == 1


def test_process_offers_accepts_normalized_offer_objects():
    service = make_service()
    offer = RetailerOffer(
        retailer="test-shop",
        raw_name="Example Fragrance",
        brand_raw="Example",
        size_ml=50,
        price=Decimal("25.00"),
    )

    result = service.process_offers([offer])

    assert result.input_count == 1
    assert result.matched_offer_count == 1
    assert result.groups[0].canonical_variant_id == "variant-example-50"


def test_service_does_not_change_the_catalog_view():
    service = make_service()
    before = service.catalog.all_products()

    service.process_records(
        [{"name": "Example Fragrance", "brand": "Example", "size_ml": 100}],
        retailer="test-shop",
    )

    assert service.catalog.all_products() == before

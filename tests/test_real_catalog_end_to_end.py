"""End-to-end read-only smoke test for the isolated ScentHunter next engine.

Loads the real canonical catalog, discovers a product/variant that the current
conservative matcher can resolve, then exercises normalization, matching and
aggregation through NextEngineService. It never writes to the catalog or DB.
"""
from pathlib import Path

from backend.scenthunter_next_engine.next_engine_service import NextEngineService


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPOSITORY_ROOT / "backend" / "product_catalog.json"


def test_real_catalog_end_to_end_pipeline_is_read_only():
    assert CATALOG_PATH.is_file(), f"Canonical catalog not found: {CATALOG_PATH}"
    service = NextEngineService.from_catalog_file(CATALOG_PATH)
    products_before = service.catalog.all_products()

    # Select a real catalog entry with one explicit, sized variant that the
    # existing matcher resolves to its actual canonical IDs. Do not invent IDs.
    selected = None
    for product in service.catalog.all_products():
        if len(product.variants) != 1:
            continue
        variant = product.variants[0]
        if variant.size_ml is None:
            continue
        record = {
            "name": product.name,
            "brand": product.brand,
            "size_ml": variant.size_ml,
            "price": "49.90",
            "url": "https://smoke-test.example/product",
        }
        result = service.process_records([record], retailer="smoke-test-shop")
        if (
            result.matched_offer_count == 1
            and result.groups
            and result.groups[0].canonical_product_id == product.product_id
            and result.groups[0].canonical_variant_id == variant.variant_id
        ):
            selected = (product, variant, record)
            break

    assert selected is not None, (
        "The real catalog has no single-variant product with an explicit size "
        "that the conservative matcher can resolve end to end."
    )

    product, variant, base_record = selected
    records = [
        dict(base_record, price="49.90", url="https://shop-a.example/product"),
        dict(base_record, price="54.90", url="https://shop-b.example/product"),
        {"brand": product.brand, "size_ml": variant.size_ml, "price": "20.00"},
        {
            "name": "Definitely Unlisted Smoke Test Fragrance",
            "brand": "Definitely Unlisted Smoke Test Brand",
            "size_ml": variant.size_ml,
            "price": "19.00",
        },
    ]

    result = service.process_records(records, retailer="smoke-test-shop")

    assert result.normalized_offer_count == 3
    assert result.matched_offer_count == 2
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.canonical_product_id == product.product_id
    assert group.canonical_variant_id == variant.variant_id
    assert len(group.offers) == 2

    assert len(result.rejected_rows) == 1
    assert len(result.unresolved) == 1
    assert result.unresolved[0].canonical_product_id is None
    assert result.unresolved[0].canonical_variant_id is None

    assert service.catalog.all_products() == products_before

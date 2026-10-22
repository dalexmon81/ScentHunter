"""Read-only real-catalog regression test for variant separation."""
from pathlib import Path

from backend.scenthunter_next_engine.next_engine_service import NextEngineService


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "backend" / "product_catalog.json"


def test_real_catalog_keeps_distinct_sizes_in_distinct_canonical_groups():
    service = NextEngineService.from_catalog_file(CATALOG)
    products_before = service.catalog.all_products()
    selected = None

    for product in products_before:
        variants_by_size = {}
        for variant in product.variants:
            if variant.size_ml is not None:
                variants_by_size.setdefault(variant.size_ml, variant)
        if len(variants_by_size) >= 2:
            selected = (product, list(variants_by_size.values())[:2])
            break

    assert selected is not None, (
        "No real catalog product with two distinct explicit variant sizes was found."
    )

    product, variants = selected
    records = [
        {
            "name": product.name,
            "brand": product.brand,
            "size_ml": variant.size_ml,
            "price": price,
            "url": f"https://{shop}.example/product",
        }
        for variant, price, shop in (
            (variants[0], "39.90", "variant-small-shop"),
            (variants[1], "59.90", "variant-large-shop"),
        )
    ]

    result = service.process_records(records, retailer="variant-separation-smoke-test")

    assert result.normalized_offer_count == 2
    assert result.matched_offer_count == 2
    assert result.rejected_rows == ()
    assert result.unresolved == ()
    assert result.ambiguous == ()
    assert len(result.groups) == 2

    actual_pairs = {
        (group.canonical_product_id, group.canonical_variant_id)
        for group in result.groups
    }
    expected_pairs = {
        (product.product_id, variants[0].variant_id),
        (product.product_id, variants[1].variant_id),
    }
    assert actual_pairs == expected_pairs
    assert all(len(group.offers) == 1 for group in result.groups)
    assert service.catalog.all_products() == products_before

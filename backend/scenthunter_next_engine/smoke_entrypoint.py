"""Read-only smoke entry point for the isolated next engine.

Loads the real canonical catalog and sends one synthetic offer through the same
service used by the engine. It does not start the API, access a database, write
files, or modify the catalog.
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.scenthunter_next_engine.next_engine_service import NextEngineService


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend" / "product_catalog.json"


def run_smoke_check() -> dict[str, object]:
    service = NextEngineService.from_catalog_file(CATALOG_PATH)

    # Use a product and variant that actually exist; never invent canonical IDs.
    candidates = [
        (product, variant)
        for product in service.catalog.all_products()
        for variant in product.variants
        if variant.size_ml is not None
    ]
    if not candidates:
        raise RuntimeError("No catalog product with an explicit millilitre variant is available")

    product, variant = candidates[0]
    records = [
        {
            "name": product.name,
            "brand": product.brand,
            "size_ml": variant.size_ml,
            "price": "19.99",
            "currency": "EUR",
            "url": "https://smoke-test.invalid/synthetic-offer",
        }
    ]

    result = service.process_records(records, retailer="next-engine-smoke-test")

    if result.normalized_offer_count != 1:
        raise AssertionError(f"Expected one normalized offer, got {result.normalized_offer_count}")
    if result.matched_offer_count != 1:
        raise AssertionError(
            "Synthetic offer did not resolve to the exact catalog identity: "
            f"matched={result.matched_offer_count}, "
            f"unresolved={len(result.unresolved)}, ambiguous={len(result.ambiguous)}, "
            f"rejected={len(result.rejected_rows)}"
        )
    if result.rejected_rows or result.unresolved or result.ambiguous:
        raise AssertionError("Smoke check produced rejected, unresolved, or ambiguous offers")

    group = result.groups[0]
    if group.canonical_product_id != product.product_id:
        raise AssertionError("Resolved product ID differs from the selected catalog product")
    if group.canonical_variant_id != variant.variant_id:
        raise AssertionError("Resolved variant ID differs from the selected catalog variant")
    if len(group.offers) != 1 or str(group.offers[0].price) != "19.99":
        raise AssertionError("Synthetic offer price was not preserved exactly")

    return {
        "status": "success",
        "mode": "read-only synthetic smoke check",
        "catalog_products": service.catalog.product_count(),
        "catalog_variants": service.catalog.variant_count(),
        "matched_offers": result.matched_offer_count,
        "canonical_product_id": product.product_id,
        "canonical_variant_id": variant.variant_id,
        "price_eur": "19.99",
        "catalog_modified": False,
        "database_accessed": False,
        "api_started": False,
    }


def main() -> None:
    print(json.dumps(run_smoke_check(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

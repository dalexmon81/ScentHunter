"""Read-only endpoint exercise with four synthetic offers against the real catalog."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.scenthunter_next_engine import runtime
from backend.scenthunter_next_engine.next_engine_service import NextEngineService


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "backend" / "product_catalog.json"


def test_preview_endpoint_handles_realistic_four_offer_batch(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "1")

    service = NextEngineService.from_catalog_file(CATALOG)
    products_before = service.catalog.all_products()
    candidates = [
        (product, variant)
        for product in products_before
        for variant in product.variants
        if variant.size_ml is not None
    ]
    assert len(candidates) >= 2, "Need two real catalog variants for this preview exercise"

    first_product, first_variant = candidates[0]
    second_product, second_variant = next(
        pair for pair in candidates[1:]
        if pair[0].product_id != first_product.product_id
    )

    records = [
        {
            "title": first_product.name,
            "brandName": first_product.brand,
            "sizeMl": first_variant.size_ml,
            "salePrice": "24.90",
            "currencyCode": "EUR",
            "productUrl": "https://synthetic-retailer.invalid/item-1",
            "inStock": True,
        },
        {
            "product_name": second_product.name,
            "manufacturer": second_product.brand,
            "volume_ml": second_variant.size_ml,
            "current_price": "39.95",
            "currency": "EUR",
            "link": "https://synthetic-retailer.invalid/item-2",
            "availability": "in_stock",
        },
        {
            "name": "Definitely Unknown ScentHunter Batch Exercise Fragrance",
            "brand": "Definitely Unknown Batch Exercise Brand",
            "price": "18.50",
            "url": "https://synthetic-retailer.invalid/unknown",
        },
        {
            "brand": "Row with missing product name",
            "price": "11.00",
        },
    ]
    records_before = [dict(record) for record in records]

    app = FastAPI()
    assert runtime.mount_next_engine(app) is True
    client = TestClient(app)
    response = client.post(
        "/next-engine/preview",
        json={"retailer": "synthetic-retailer-batch", "records": records},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "read-only-preview"
    assert data["catalog_modified"] is False
    assert data["database_accessed"] is False
    assert data["input_count"] == 4
    assert data["normalized_offer_count"] == 3
    assert data["matched_offer_count"] == 2
    assert len(data["groups"]) == 2
    assert len(data["unresolved"]) == 1
    assert len(data["ambiguous"]) == 0
    assert len(data["rejected_rows"]) == 1

    grouped = {
        (group["canonical_product_id"], group["canonical_variant_id"]): group
        for group in data["groups"]
    }
    first_key = (first_product.product_id, first_variant.variant_id)
    second_key = (second_product.product_id, second_variant.variant_id)
    assert first_key in grouped
    assert second_key in grouped
    assert grouped[first_key]["offers"][0]["price"] == "24.90"
    assert grouped[second_key]["offers"][0]["price"] == "39.95"
    assert grouped[first_key]["offers"][0]["retailer"] == "synthetic-retailer-batch"
    assert grouped[second_key]["offers"][0]["retailer"] == "synthetic-retailer-batch"

    assert records == records_before
    assert service.catalog.all_products() == products_before

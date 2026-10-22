from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.scenthunter_next_engine import runtime
from backend.scenthunter_next_engine.next_engine_service import NextEngineService


def test_runtime_stays_unmounted_without_second_opt_in(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "0")
    app = FastAPI()

    assert runtime.mount_next_engine(app) is False
    assert not any(route.path == "/next-engine/preview" for route in app.routes)


def test_preview_rejects_missing_retailer_and_non_list_records(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "1")
    app = FastAPI()
    assert runtime.mount_next_engine(app) is True
    client = TestClient(app)

    missing_retailer = client.post(
        "/next-engine/preview",
        json={"records": [{"name": "Example"}]},
    )
    assert missing_retailer.status_code == 422

    non_list_records = client.post(
        "/next-engine/preview",
        json={"retailer": "example-shop", "records": {"name": "Example"}},
    )
    assert non_list_records.status_code == 422


def test_preview_rejects_batches_over_limit(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "1")
    app = FastAPI()
    assert runtime.mount_next_engine(app) is True
    client = TestClient(app)

    response = client.post(
        "/next-engine/preview",
        json={"retailer": "example-shop", "records": [{}] * 101},
    )
    assert response.status_code == 413


def test_preview_returns_read_only_service_results(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "1")
    app = FastAPI()

    class FakeProduct:
        brand = "Example Brand"
        name = "Example Fragrance"

    class FakeOffer:
        retailer = "example-shop"
        price = None
        currency = "EUR"
        availability = None
        product_url = None
        raw_name = "Example Fragrance"
        brand_raw = "Example Brand"
        size_ml = 50

    class FakeGroup:
        canonical_product_id = "prod-real-1"
        canonical_variant_id = "var-real-1"
        offers = (FakeOffer(),)

    class FakeMatch:
        offer = FakeOffer()
        status = type("Status", (), {"value": "unresolved"})()
        reason = "not_confident"
        candidate_product_ids = ()

    class FakeResult:
        groups = (FakeGroup(),)
        unresolved = (FakeMatch(),)
        ambiguous = ()
        rejected_rows = ()
        normalized_offer_count = 1
        matched_offer_count = 1

    class FakeCatalog:
        def get(self, product_id):
            assert product_id == "prod-real-1"
            return FakeProduct()

    class FakeService:
        catalog = FakeCatalog()

        def process_records(self, records, *, retailer):
            assert retailer == "example-shop"
            assert records == [{"name": "Example Fragrance"}]
            return FakeResult()

    monkeypatch.setattr(
        runtime.NextEngineService,
        "from_catalog_file",
        staticmethod(lambda path: FakeService()),
    )

    assert runtime.mount_next_engine(app) is True
    client = TestClient(app)
    response = client.post(
        "/next-engine/preview",
        json={
            "retailer": "example-shop",
            "records": [{"name": "Example Fragrance"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "read-only-preview"
    assert data["catalog_modified"] is False
    assert data["database_accessed"] is False
    assert data["matched_offer_count"] == 1
    assert data["groups"][0]["canonical_variant_id"] == "var-real-1"
    assert data["unresolved"][0]["status"] == "unresolved"


def test_preview_endpoint_against_real_catalog_is_read_only(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "1")
    root = Path(runtime.__file__).resolve().parents[2]
    catalog_path = root / "backend" / "product_catalog.json"
    service = NextEngineService.from_catalog_file(catalog_path)

    candidates = [
        (product, variant)
        for product in service.catalog.all_products()
        for variant in product.variants
        if variant.size_ml is not None
    ]
    assert candidates, "Real catalog must contain at least one explicit size variant"
    product, variant = candidates[0]

    app = FastAPI()
    assert runtime.mount_next_engine(app) is True
    client = TestClient(app)
    response = client.post(
        "/next-engine/preview",
        json={
            "retailer": "runtime-preview-test",
            "records": [
                {
                    "name": product.name,
                    "brand": product.brand,
                    "size_ml": variant.size_ml,
                    "price": "19.99",
                    "currency": "EUR",
                    "url": "https://preview-test.invalid/synthetic-offer",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "read-only-preview"
    assert data["catalog_modified"] is False
    assert data["database_accessed"] is False
    assert data["input_count"] == 1
    assert data["normalized_offer_count"] == 1
    assert data["matched_offer_count"] == 1
    assert data["unresolved"] == []
    assert data["ambiguous"] == []
    assert data["rejected_rows"] == []
    assert len(data["groups"]) == 1
    group = data["groups"][0]
    assert group["canonical_product_id"] == product.product_id
    assert group["canonical_variant_id"] == variant.variant_id
    assert group["offers"][0]["price"] == "19.99"
    assert group["offers"][0]["retailer"] == "runtime-preview-test"

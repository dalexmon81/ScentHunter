"""PostgreSQL-backed HTTP contract for the catalog-first search API.

This test uses only the disposable PostgreSQL service configured by CI.
It inserts a small, isolated canonical record and a validated offer, then
exercises the same FastAPI router used by the application. No retailer network
calls, worker startup, scheduler, or production database is involved.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.api import catalog_search
from app.models import Brand, Fragrance, ProductVariant, Store, IngestionRaw, Offer, MatchAudit

DATABASE_URL = os.environ.get("SCENTHUNTER_TEST_POSTGRES_URL", "")


@pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL service")
def test_catalog_search_http_reads_validated_offer_from_postgresql():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    app = FastAPI()
    app.include_router(catalog_search.router)
    try:
        # Unique test identity; clean up only rows created by this test.
        with Session(engine) as session, session.begin():
            brand = Brand(
                name="ScentHunter API Test Brand",
                slug="scenthunter-api-test-brand",
                normalized_name="scenthunter api test brand",
            )
            session.add(brand)
            session.flush()

            fragrance = Fragrance(
                brand_id=brand.id,
                name="API Contract Fragrance",
                slug="api-contract-fragrance",
            )
            session.add(fragrance)
            session.flush()

            variant = ProductVariant(
                fragrance_id=fragrance.id,
                concentration="Eau de Parfum",
                size_ml=100,
                is_tester=False,
                is_refill=False,
                is_gift_set=False,
                is_mini=False,
                canonical_key="scenthunter-api-test-brand|api-contract-fragrance|edp|100|api-test",
            )
            store = Store(
                name="Bplatz API Test",
                slug="bplatz-api-test",
                domain="bplatz.de",
                country="DE",
                currency="EUR",
                status="active",
            )
            session.add_all([variant, store])
            session.flush()

            raw = IngestionRaw(
                store_id=store.id,
                raw_payload={
                    "currency_explicit": True,
                    "availability": "in_stock",
                    "source": "postgresql_http_api_contract_test",
                },
                external_product_id="api-contract-product-100",
                status="promoted",
                product_variant_id=variant.id,
                match_method="test_exact",
                match_confidence=Decimal("1.000"),
            )
            session.add(raw)
            session.flush()

            captured_at = datetime.now(timezone.utc)
            offer = Offer(
                ingestion_raw_id=raw.id,
                store_id=store.id,
                product_variant_id=variant.id,
                external_product_id="api-contract-product-100",
                url="https://bplatz.de/products/api-contract-fragrance",
                price=Decimal("42.50"),
                currency="EUR",
                availability="in_stock",
                source="postgresql_http_api_contract_test",
                captured_at=captured_at,
                status="active",
            )
            session.add(offer)
            session.flush()
            session.add(MatchAudit(
                offer_id=offer.id,
                product_variant_id=variant.id,
                method="test_exact",
                confidence=Decimal("1.000"),
                reason="Isolated PostgreSQL HTTP API contract fixture",
            ))
            expected_variant_id = str(variant.id)
            expected_offer_id = offer.id
            expected_store_name = store.name

        with patch.object(catalog_search, "_engine", return_value=engine):
            with TestClient(app) as client:
                status = client.get("/api/catalog/status")
                assert status.status_code == 200, status.text
                status_data = status.json()
                assert status_data["status"] == "ready"
                assert status_data["published_offers"] >= 1

                response = client.get(
                    "/api/catalog/search",
                    params={"q": "ScentHunter API Test Brand API Contract Fragrance EDP 100 ml"},
                )
                assert response.status_code == 200, response.text
                data = response.json()
                assert data["status"] == "completed"
                assert data["count"] == 1
                assert data["offer_count"] == 1
                item = data["results"][0]
                assert item["catalog_id"] == expected_variant_id
                assert item["brand"] == "ScentHunter API Test Brand"
                assert item["name"] == "API Contract Fragrance Eau de Parfum 100 ml"
                assert len(item["offers"]) == 1
                public_offer = item["offers"][0]
                assert public_offer["store"] == expected_store_name
                assert public_offer["price"] == "42.50"
                assert public_offer["currency"] == "EUR"
                assert public_offer["availability"] == "in_stock"
                assert public_offer["url"] == "https://bplatz.de/products/api-contract-fragrance"
                assert public_offer["captured_at"]
                assert expected_offer_id is not None

                demo = client.get("/catalog-demo")
                assert demo.status_code == 200
                assert "ScentHunter" in demo.text
                assert "/api/catalog/search?q=" in demo.text
    finally:
        # Remove only this test's records; CI database is disposable.
        with Session(engine) as session, session.begin():
            row = session.query(Offer).filter(
                Offer.external_product_id == "api-contract-product-100"
            ).first()
            if row is not None:
                session.delete(row)
            raw_row = session.query(IngestionRaw).filter(
                IngestionRaw.external_product_id == "api-contract-product-100"
            ).first()
            if raw_row is not None:
                session.delete(raw_row)
            store_row = session.query(Store).filter(Store.slug == "bplatz-api-test").first()
            if store_row is not None:
                session.delete(store_row)
            variant_row = session.query(ProductVariant).filter(
                ProductVariant.canonical_key.endswith("|api-test")
            ).first()
            if variant_row is not None:
                session.delete(variant_row)
            fragrance_row = session.query(Fragrance).filter(
                Fragrance.slug == "api-contract-fragrance"
            ).first()
            if fragrance_row is not None:
                session.delete(fragrance_row)
            brand_row = session.query(Brand).filter(
                Brand.slug == "scenthunter-api-test-brand"
            ).first()
            if brand_row is not None:
                session.delete(brand_row)
        engine.dispose()

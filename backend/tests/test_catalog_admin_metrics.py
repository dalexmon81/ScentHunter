from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Brand,
    CanonicalIdentityReview,
    Fragrance,
    IngestionDeadLetter,
    IngestionRaw,
    Offer,
    ProductVariant,
    Store,
)
from app.services.catalog_metrics import catalog_metrics_snapshot


def test_metrics_snapshot_reports_aggregate_health_without_raw_payloads():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

    try:
        with factory() as session:
            brand = Brand(name="Fixture Brand", slug="fixture-brand", normalized_name="fixture-brand")
            session.add(brand)
            session.flush()
            fragrance = Fragrance(brand_id=brand.id, name="Fixture Scent", slug="fixture-scent")
            session.add(fragrance)
            session.flush()
            variant = ProductVariant(fragrance_id=fragrance.id, canonical_key="fixture-brand|fixture-scent|edp|100")
            store = Store(name="Fixture Store", slug="metrics-fixture-store", currency="EUR", status="active", reliability_score=0.9)
            session.add_all([variant, store])
            session.flush()

            session.add_all([
                Offer(
                    store_id=store.id,
                    product_variant_id=variant.id,
                    url="https://fixture.example/scent",
                    price=25,
                    currency="EUR",
                    availability="in_stock",
                    source="test_fixture",
                    status="active",
                    captured_at=now - timedelta(hours=30),
                ),
                IngestionRaw(store_id=store.id, raw_payload={"private": "must_not_escape"}, status="pending"),
                IngestionDeadLetter(
                    task_name="fixture.task",
                    task_id="fixture-task-1",
                    args_repr="[]",
                    kwargs_repr="{}",
                    error="fixture failure",
                    status="open",
                ),
                CanonicalIdentityReview(
                    fingerprint="a" * 64,
                    canonical_key="fixture-brand|fixture-scent|edp|100",
                    normalized_payload={"brand": "Fixture Brand"},
                    reason="ambiguous_fixture",
                    status="pending",
                ),
            ])
            session.commit()

            snapshot = catalog_metrics_snapshot(session, now=now)

        assert snapshot["read_only"] is True
        assert snapshot["stores"]["active"] == 1
        assert snapshot["offers"] == {"active": 1, "stale_over_24h_or_expired": 1}
        assert snapshot["ingestion"] == {"pending_or_unmatched": 1, "open_dead_letters": 1}
        assert snapshot["matching"]["pending_identity_reviews"] == 1
        assert "private" not in str(snapshot)
        assert snapshot["stores"]["by_store"][0]["slug"] == "metrics-fixture-store"
    finally:
        engine.dispose()


def test_admin_overview_requires_configured_token(monkeypatch):
    from app.api.catalog_admin import router

    monkeypatch.delenv("SCENTHUNTER_CATALOG_ADMIN_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/catalog/admin/overview")
    assert response.status_code == 503
    assert response.json()["detail"] == "catalog_admin_token_not_configured"


def test_admin_overview_rejects_wrong_token_before_database_access(monkeypatch):
    from app.api.catalog_admin import router

    monkeypatch.setenv("SCENTHUNTER_CATALOG_ADMIN_TOKEN", "test-only-secret")
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get(
        "/catalog/admin/overview",
        headers={"X-ScentHunter-Admin-Token": "wrong"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden"


def test_admin_overview_is_mounted_in_real_application_and_fails_closed(monkeypatch):
    monkeypatch.delenv("SCENTHUNTER_CATALOG_ADMIN_TOKEN", raising=False)
    from main import app as scenthunter_app

    response = TestClient(scenthunter_app).get("/catalog/admin/overview")
    assert response.status_code == 503
    assert response.json()["detail"] == "catalog_admin_token_not_configured"

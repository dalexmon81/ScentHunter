from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api.admin_catalog as admin_catalog
from app.api.admin_catalog import router
from app.models import (
    Base,
    CanonicalIdentityReview,
    IngestionDeadLetter,
    IngestionRaw,
    IngestionRun,
    MatchAudit,
    Offer,
    Store,
)


def _client():
    api = FastAPI()
    api.include_router(router)
    return TestClient(api)


def test_admin_api_fails_closed_without_configured_token(monkeypatch):
    monkeypatch.delenv("SCENTHUNTER_ADMIN_TOKEN", raising=False)
    response = _client().get("/catalog/admin/metrics")
    assert response.status_code == 503
    assert response.json()["detail"] == "catalog_admin_disabled"


def test_admin_api_rejects_invalid_token(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_ADMIN_TOKEN", "ci-admin-secret")
    response = _client().get(
        "/catalog/admin/metrics",
        headers={"X-ScentHunter-Admin-Token": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_admin_token"


def test_admin_metrics_and_review_queues_report_persisted_state(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-admin.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with factory.begin() as session:
        store = Store(
            name="CI Operations Store",
            slug="ci-operations-store",
            status="active",
            reliability_score=Decimal("0.800"),
            last_successful_sync_at=now - timedelta(hours=1),
        )
        session.add(store)
        session.flush()

        offer = Offer(
            store_id=store.id,
            url="https://example.invalid/ci-operations-offer",
            price=Decimal("19.90"),
            currency="EUR",
            availability="in_stock",
            source="ci_fixture",
            confidence=Decimal("0.400"),
            captured_at=now - timedelta(days=2),
            status="active",
        )
        session.add(offer)
        session.flush()

        session.add_all(
            [
                IngestionRaw(
                    store_id=store.id,
                    raw_payload={"fixture": True},
                    status="pending",
                ),
                IngestionRun(
                    store_id=store.id,
                    started_at=now - timedelta(hours=1),
                    status="failed",
                    products_discovered=1,
                    offers_created=0,
                    offers_updated=0,
                    offers_rejected=1,
                    errors=[{"reason": "fixture_failure"}],
                ),
                IngestionDeadLetter(
                    task_name="app.workers.ingestion_tasks.refresh_offer",
                    task_id="ci-dead-letter-001",
                    args_repr="[]",
                    kwargs_repr="{}",
                    error="fixture failure",
                    status="open",
                    created_at=now - timedelta(minutes=1),
                ),
                CanonicalIdentityReview(
                    fingerprint="a" * 64,
                    canonical_key="brand|fragrance|edp|100|standard",
                    normalized_payload={"brand": "Brand", "name": "Fragrance"},
                    reason="ambiguous_match",
                    status="pending",
                ),
                MatchAudit(
                    offer_id=offer.id,
                    method="fuzzy",
                    confidence=Decimal("0.400"),
                    reason="below_auto_match_threshold",
                ),
            ]
        )

    monkeypatch.setattr(admin_catalog, "make_session_factory", lambda: factory)
    monkeypatch.setenv("SCENTHUNTER_ADMIN_TOKEN", "ci-admin-secret")
    client = _client()
    headers = {"X-ScentHunter-Admin-Token": "ci-admin-secret"}

    try:
        metrics_response = client.get("/catalog/admin/metrics", headers=headers)
        assert metrics_response.status_code == 200, metrics_response.text
        metrics = metrics_response.json()
        totals = metrics["totals"]
        assert totals["active_stores"] == 1
        assert totals["stores_missing_offer_ttl"] == 1
        assert totals["active_offers"] == 0
        assert totals["stale_offers_24h"] == 1
        assert totals["offers_missing_expiry"] == 1
        assert totals["offers_without_canonical_variant"] == 1
        assert totals["pending_raw_records"] == 1
        assert totals["pending_identity_reviews"] == 1
        assert totals["pending_match_reviews"] == 1
        assert totals["open_dead_letters"] == 1
        assert totals["failed_ingestion_runs_24h"] == 1
        assert metrics["stores"][0]["slug"] == "ci-operations-store"
        assert metrics["stores"][0]["stale_offers_24h"] == 1

        review_response = client.get("/catalog/admin/review-queue", headers=headers)
        assert review_response.status_code == 200
        review_payload = review_response.json()
        assert len(review_payload["identity_reviews"]) == 1
        assert len(review_payload["match_reviews"]) == 1

        dead_letter_response = client.get("/catalog/admin/dead-letters", headers=headers)
        assert dead_letter_response.status_code == 200
        assert dead_letter_response.json()["count"] == 1
        assert dead_letter_response.json()["items"][0]["task_id"] == "ci-dead-letter-001"
    finally:
        engine.dispose()


def test_admin_can_configure_store_offer_ttl(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-ttl-admin.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add(Store(name="TTL Store", slug="ttl-store", status="active"))

    monkeypatch.setattr(admin_catalog, "make_session_factory", lambda: factory)
    monkeypatch.setenv("SCENTHUNTER_ADMIN_TOKEN", "ci-admin-secret")
    try:
        response = _client().put(
            "/catalog/admin/stores/ttl-store/freshness-policy",
            params={"offer_ttl_minutes": 180},
            headers={"X-ScentHunter-Admin-Token": "ci-admin-secret"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["offer_ttl_minutes"] == 180
        with factory() as session:
            store = session.scalar(
                select(Store).where(Store.slug == "ttl-store")
            )
            assert store.offer_ttl_minutes == 180

        missing = _client().put(
            "/catalog/admin/stores/not-configured/freshness-policy",
            params={"offer_ttl_minutes": 180},
            headers={"X-ScentHunter-Admin-Token": "ci-admin-secret"},
        )
        assert missing.status_code == 404
    finally:
        engine.dispose()

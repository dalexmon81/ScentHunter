from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, IngestionRun, MatchAudit, Offer, Store
from app.api import admin


@pytest.fixture
def admin_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'admin.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store_id, offer_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with factory.begin() as session:
        session.add(Store(
            id=store_id, name="Test Store", slug="test-store",
            country="FR", currency="EUR", status="active",
        ))
        session.add(Offer(
            id=offer_id, store_id=store_id, url="https://example.test/item",
            price=Decimal("49.90"), currency="EUR", availability="in_stock",
            source="fixture", captured_at=now, status="active",
            publication_status="published",
        ))
        session.add(MatchAudit(
            offer_id=offer_id, method="gtin_exact", confidence=Decimal("0.990"),
        ))
        session.add(IngestionRun(
            store_id=store_id, status="completed", products_discovered=5,
            offers_created=1, offers_updated=0, offers_rejected=0,
            started_at=now - timedelta(minutes=5), finished_at=now, errors=[],
        ))
    monkeypatch.setattr(admin, "_session_factory", lambda: factory)
    yield factory
    engine.dispose()


def test_admin_metrics_uses_persisted_counts_and_match_rates(admin_db):
    result = admin.operational_metrics(_auth=None)
    assert result["offers"]["total"] == 1
    assert result["offers"]["published"] == 1
    assert result["matching"]["automatic_count"] == 1
    assert result["matching"]["automatic_rate"] == 1.0
    assert result["price_freshness"]["offers_with_valid_stock"] == 1
    assert result["connectors"]["runs_last_24h"] == 1
    assert result["search_latency"]["available"] is False


def test_admin_alerts_returns_empty_for_healthy_store(admin_db):
    result = admin.operational_alerts(_auth=None)
    assert result["count"] == 0
    assert result["alerts"] == []


def test_admin_router_exposes_metrics_alerts_and_guarded_actions():
    paths = {route.path for route in admin.router.routes}
    assert "/api/admin/metrics" in paths
    assert "/api/admin/alerts" in paths
    assert "/api/admin/connectors/{store_key}/restart" in paths
    assert "/api/admin/reprocess" in paths

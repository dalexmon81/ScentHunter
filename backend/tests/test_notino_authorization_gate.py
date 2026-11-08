"""Production Celery Notino discovery must fail closed before any feed request."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Store, StoreAuthorization
from app.workers import ingestion_tasks


class FeedProbe:
    def __init__(self):
        self.discovery_calls = 0

    async def discover_products(self):
        self.discovery_calls += 1
        raise AssertionError("Notino feed must not be requested without authorization")


def _factory(tmp_path, *, scopes=None, status="approved", expires_at=None, revoked_at=None):
    engine = create_engine(f"sqlite:///{tmp_path / 'notino-auth.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        store = Store(
            name="Notino", slug="notino", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        session.add(store)
        session.flush()
        if scopes is not None:
            session.add(StoreAuthorization(
                store_id=store.id,
                status=status,
                collection_method="affiliate_feed",
                scopes=scopes,
                authorization_reference="fixture-approval",
                approved_by="isolated-test",
                approved_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                revoked_at=revoked_at,
                terms={},
            ))
        session.commit()
    return factory


@pytest.mark.parametrize(
    ("grant", "message"),
    [
        ({}, "store_collection_not_authorized:notino"),
        (
            {"scopes": ["product_discovery"]},
            "store_authorization_scope_missing:notino:offer_data",
        ),
        (
            {"scopes": ["product_discovery", "offer_data"], "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)},
            "store_collection_not_authorized:notino",
        ),
        (
            {"scopes": ["product_discovery", "offer_data"], "revoked_at": datetime.now(timezone.utc)},
            "store_collection_not_authorized:notino",
        ),
        (
            {"scopes": ["product_discovery", "offer_data"], "status": "pending"},
            "store_collection_not_authorized:notino",
        ),
    ],
)
def test_notino_discovery_does_not_request_feed_without_current_full_authorization(
    monkeypatch, tmp_path, grant, message
):
    factory = _factory(tmp_path, **grant)
    probe = FeedProbe()
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "get_connector", lambda _key: probe)

    with pytest.raises(PermissionError, match=message):
        ingestion_tasks.discover_store_products.run("notino")

    assert probe.discovery_calls == 0
    factory.kw["bind"].dispose()

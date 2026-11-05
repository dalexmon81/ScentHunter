from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Offer, Store
from app.api.offer_refresh import queue_offer_refresh


def _refresh_factory(tmp_path, *, store_status="active", offer_status="active", external_id="sku-123"):
    engine = create_engine(f"sqlite:///{tmp_path / 'refresh-test.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store_id = uuid4()
    offer_id = uuid4()
    with factory() as session:
        session.add(Store(id=store_id, name="Notino", slug="notino", currency="EUR", status=store_status))
        session.add(Offer(
            id=offer_id,
            store_id=store_id,
            external_product_id=external_id,
            url="https://shop.example/product/sku-123",
            price=Decimal("99.00"),
            currency="EUR",
            availability="in_stock",
            source="fixture",
            status=offer_status,
        ))
        session.commit()
    return factory, offer_id


class FakeRedis:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.values = {}
        self.deleted = []
        self.closed = False

    def set(self, key, value, *, nx, ex):
        self.values[key] = (value, nx, ex)
        return self.acquired

    def delete(self, key):
        self.deleted.append(key)

    def close(self):
        self.closed = True


def test_refresh_endpoint_queues_only_database_resolved_offer(tmp_path):
    factory, offer_id = _refresh_factory(tmp_path)
    redis = FakeRedis()
    enqueued = []
    result = queue_offer_refresh(
        offer_id,
        session_factory=factory,
        redis_factory=lambda: redis,
        enqueue=lambda store, external_id: enqueued.append((store, external_id)) or "job-42",
    )
    assert result == {"status": "queued", "offer_id": str(offer_id), "job_id": "job-42"}
    assert enqueued == [("notino", "sku-123")]
    assert list(redis.values.values()) == [("queued", True, 300)]
    assert redis.closed


def test_refresh_endpoint_rejects_unknown_or_inactive_offer(tmp_path):
    factory, offer_id = _refresh_factory(tmp_path, store_status="quarantined")
    redis = FakeRedis()
    with pytest.raises(HTTPException) as exc:
        queue_offer_refresh(
            offer_id,
            session_factory=factory,
            redis_factory=lambda: redis,
            enqueue=lambda *_: pytest.fail("must not enqueue inactive store"),
        )
    assert exc.value.status_code == 404
    assert not redis.values


def test_refresh_endpoint_rejects_offer_without_stable_retailer_id(tmp_path):
    factory, offer_id = _refresh_factory(tmp_path, external_id=None)
    redis = FakeRedis()
    with pytest.raises(HTTPException) as exc:
        queue_offer_refresh(
            offer_id,
            session_factory=factory,
            redis_factory=lambda: redis,
            enqueue=lambda *_: pytest.fail("must not enqueue without retailer ID"),
        )
    assert exc.value.status_code == 409
    assert not redis.values


def test_refresh_endpoint_applies_per_offer_cooldown(tmp_path):
    factory, offer_id = _refresh_factory(tmp_path)
    redis = FakeRedis(acquired=False)
    enqueued = []
    result = queue_offer_refresh(
        offer_id,
        session_factory=factory,
        redis_factory=lambda: redis,
        enqueue=lambda *args: enqueued.append(args),
    )
    assert result == {"status": "already_queued", "offer_id": str(offer_id)}
    assert not enqueued


def test_refresh_endpoint_releases_cooldown_if_enqueue_fails(tmp_path):
    factory, offer_id = _refresh_factory(tmp_path)
    redis = FakeRedis()
    with pytest.raises(HTTPException) as exc:
        queue_offer_refresh(
            offer_id,
            session_factory=factory,
            redis_factory=lambda: redis,
            enqueue=lambda *_: (_ for _ in ()).throw(RuntimeError("broker down")),
        )
    assert exc.value.status_code == 503
    assert len(redis.deleted) == 1



def test_refresh_endpoint_fails_closed_when_redis_client_cannot_be_created(tmp_path):
    factory, offer_id = _refresh_factory(tmp_path)
    with pytest.raises(HTTPException) as exc:
        queue_offer_refresh(
            offer_id,
            session_factory=factory,
            redis_factory=lambda: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
            enqueue=lambda *_: pytest.fail("must not enqueue without Redis cooldown"),
        )
    assert exc.value.status_code == 503
    assert exc.value.detail == "refresh_queue_unavailable"

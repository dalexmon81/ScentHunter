import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.base import OfferRecord
from app.models import Base, IngestionRaw, IngestionRun, Store
from app.workers.connector_ingestion import run_connector_once


class FakeConnector:
    store_key = "fake-store"
    source_kind = "fixture"

    def __init__(self, *, fail=False, invalid=False):
        self.fail = fail
        self.invalid = invalid

    async def discover_products(self):
        if self.fail:
            raise TimeoutError("temporary retailer timeout")
        return ({"externalProductId": "sku-1"},)

    async def fetch_offers(self, product_key):
        return (self.record(),)

    async def fetch_product(self, external_id):
        return None

    async def fetch_price_and_stock(self, offer_id):
        return None

    def parse_raw(self, raw):
        return ()

    def record(self):
        return OfferRecord(
            store=self.store_key,
            external_product_id="sku-1",
            brand="Dior",
            fragrance="sauvage",
            concentration="edp",
            size_ml=100,
            gtin=None,
            title="Dior Sauvage EDP 100 ml",
            url="https://shop.example/product/sku-1",
            price=Decimal("95.00"),
            currency="EUR",
            availability="unknown" if self.invalid else "in_stock",
            captured_at=datetime.now(timezone.utc).isoformat(),
            source=self.source_kind,
        )

    def validate_offer(self, offer):
        if self.invalid:
            return False, ("fixture_invalid",)
        return True, ()


def make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Store(name="Fake Store", slug="fake-store", currency="EUR", status="active"))
        session.commit()
    return factory


def test_worker_stages_valid_evidence_without_publishing():
    factory = make_session_factory()
    result = run_connector_once(FakeConnector(), factory)
    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
        run = session.scalar(select(IngestionRun))
    assert result == {
        "store": "fake-store", "status": "completed", "discovered": 1,
        "staged": 1, "rejected": 0, "published": 0,
    }
    assert raw.status == "pending"
    assert raw.external_product_id == "sku-1"
    assert run.status == "completed"
    assert run.offers_created == 0


def test_worker_keeps_invalid_evidence_rejected():
    factory = make_session_factory()
    result = run_connector_once(FakeConnector(invalid=True), factory)
    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
    assert result["rejected"] == 1
    assert raw.status == "rejected"
    assert raw.rejection_reason == "fixture_invalid"


def test_worker_quarantines_only_after_repeated_store_failures():
    factory = make_session_factory()
    first = run_connector_once(FakeConnector(fail=True), factory, quarantine_after=2)
    second = run_connector_once(FakeConnector(fail=True), factory, quarantine_after=2)
    with factory() as session:
        store = session.scalar(select(Store))
    assert first["status"] == "failed"
    assert second["status"] == "quarantined"
    assert store.status == "quarantined"

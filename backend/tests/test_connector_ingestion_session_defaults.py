from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.base import OfferRecord
from app.models import Base, IngestionRaw, IngestionRun, Store
from app.workers.connector_ingestion import run_connector_once


class Connector:
    store_key = "session-test"
    source_kind = "fixture"

    async def discover_products(self):
        return ({"externalProductId": "sku-1"},)

    async def fetch_offers(self, product_key):
        return (OfferRecord(
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
            availability="in_stock",
            captured_at=datetime.now(timezone.utc).isoformat(),
            source=self.source_kind,
        ),)

    async def fetch_product(self, external_id):
        return None

    async def fetch_price_and_stock(self, offer_id):
        return None

    def parse_raw(self, raw):
        return ()

    def validate_offer(self, offer):
        return True, ()


def test_ingestion_worker_with_default_expire_on_commit_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(Store(
            name="Session Test",
            slug="session-test",
            currency="EUR",
            status="active",
        ))
        session.commit()

    result = run_connector_once(Connector(), factory)

    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
        run = session.scalar(select(IngestionRun))

    assert result["status"] == "completed"
    assert raw.status == "pending"
    assert run.status == "completed"

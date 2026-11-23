from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.connectors.base import DiscoveredProduct
from app.models import Base, IngestionRun, Store
from app.services.connector_ingestion import ConnectorIngestionResult
from app.workers import legacy_runtime, notino_runtime


class FakeLegacyConnector:
    store_key = "deloox"

    async def discover_products(self, *, cursor=None, limit=100):
        return (
            DiscoveredProduct(
                external_product_id="https://www.deloox.be/product/123",
                product_url="https://www.deloox.be/product/123",
                raw_payload={"url": "https://www.deloox.be/product/123"},
            ),
        )

    async def fetch_product(self, external_product_id):
        return {
            "external_product_id": external_product_id,
            "name": "Dior Sauvage Eau de Parfum 100 ml",
            "url": external_product_id,
            "price_num": 89.9,
            "currency": "EUR",
            "availability": "in_stock",
            "raw_data": {"jsonld": {"offers": {"priceCurrency": "EUR"}}},
        }


class LegacyWorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as session, session.begin():
            self.store = Store(
                name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
                country="BE", currency="EUR", status="active",
            )
            session.add(self.store)
            session.flush()
            self.store_id = self.store.id

    def tearDown(self):
        self.engine.dispose()

    def test_legacy_discovery_stages_candidates_for_shared_canonical_gate(self):
        patches = [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(legacy_runtime, "build_legacy_connector", return_value=FakeLegacyConnector()),
            patch.object(legacy_runtime, "enqueue_offer_fetch"),
        ]
        started = [item.start() for item in patches]
        enqueue_fetch = started[-1]
        try:
            result = legacy_runtime.handle_legacy_discovery({
                "store_id": str(self.store_id), "limit": 10,
            })
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["store"], "deloox-be")
        self.assertEqual(result["products_discovered"], 1)
        self.assertEqual(result["fetch_jobs_queued"], 1)
        self.assertNotIn("canonical_candidates_skipped", result)
        enqueue_fetch.assert_called_once_with(
            self.store_id, "https://www.deloox.be/product/123"
        )
        with self.sessions() as session:
            run = session.get(IngestionRun, __import__("uuid").UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.products_discovered, 1)

    def test_legacy_fetch_uses_shared_catalog_persistence_gate(self):
        fake_result = ConnectorIngestionResult(
            ingestion_raw_id=uuid4(), status="promoted",
            offer_id=uuid4(), product_variant_id=uuid4(),
        )
        patches = [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(notino_runtime, "_matcher", return_value=object()),
            patch.object(legacy_runtime, "build_legacy_connector", return_value=FakeLegacyConnector()),
            patch.object(legacy_runtime, "persist_connector_record", return_value=fake_result),
        ]
        started = [item.start() for item in patches]
        persist = started[-1]
        try:
            result = legacy_runtime.handle_legacy_fetch({
                "store_id": str(self.store_id),
                "external_product_id": "https://www.deloox.be/product/123",
            })
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["store"], "deloox-be")
        persist.assert_called_once()
        with self.sessions() as session:
            run = session.get(IngestionRun, __import__("uuid").UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.offers_created, 1)


if __name__ == "__main__":
    unittest.main()

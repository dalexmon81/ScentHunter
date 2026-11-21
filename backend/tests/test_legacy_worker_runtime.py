from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.connectors.base import DiscoveredProduct
from app.models import Base, IngestionRun, Offer, Store
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

    def test_legacy_discovery_queues_only_canonical_candidates(self):
        patches = [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(notino_runtime, "_matcher", return_value=object()),
            patch.object(notino_runtime, "_is_unique_canonical_candidate", return_value=True),
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
        enqueue_fetch.assert_called_once_with(
            self.store_id, "https://www.deloox.be/product/123"
        )
        with self.sessions() as session:
            run = session.get(IngestionRun, __import__("uuid").UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.products_discovered, 1)

    def test_legacy_discovery_passes_store_id_to_canonical_matcher(self):
        patches = [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(notino_runtime, "_is_unique_canonical_candidate", return_value=True),
            patch.object(legacy_runtime, "build_legacy_connector", return_value=FakeLegacyConnector()),
            patch.object(legacy_runtime, "enqueue_offer_fetch"),
        ]
        started = [item.start() for item in patches]
        candidate = started[1]
        try:
            result = legacy_runtime.handle_legacy_discovery({
                "store_id": str(self.store_id), "limit": 10,
            })
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertEqual(result["status"], "completed")
        candidate.assert_called_once_with(
            unittest.mock.ANY, self.store_id,
            {"url": "https://www.deloox.be/product/123"},
        )

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


    def test_legacy_refresh_uses_persisted_offer_url(self):
        product_url = "https://www.deloox.be/product/persisted-123"
        with self.sessions() as session, session.begin():
            session.add(Offer(
                store_id=self.store_id,
                external_product_id="123:456",
                url=product_url,
                price="89.90",
                currency="EUR",
                availability="in_stock",
                source="test",
                status="active",
            ))

        class RefreshConnector(FakeLegacyConnector):
            seen = None

            async def fetch_offer_price_and_stock(self, external_id, persisted_url=None):
                self.seen = (external_id, persisted_url)
                return {"raw_record": {"price": "88.90"}, "captured_at": 1}

            def parse_raw(self, raw):
                return {
                    "price": "88.90",
                    "currency": "EUR",
                    "currency_explicit": True,
                    "availability": "in_stock",
                    "product_url": product_url,
                    "url": product_url,
                    "source": "test",
                }

            def validate_offer(self, parsed):
                return type("Validation", (), {"valid": True})()

        connector = RefreshConnector()
        with (
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(legacy_runtime, "build_legacy_connector", return_value=connector),
            patch.object(legacy_runtime, "refresh_offer_observation") as refresh,
        ):
            result = legacy_runtime.handle_legacy_refresh({
                "store_id": str(self.store_id),
                "external_product_id": "123:456",
            })

        self.assertEqual(result["status"], "refreshed")
        self.assertEqual(connector.seen, ("123:456", product_url))
        refresh.assert_called_once()


    def test_shopify_refresh_rejects_unverified_currency_provenance(self):
        product_url = "https://orioudh.com/products/test-product"
        with self.sessions() as session, session.begin():
            session.add(Offer(
                store_id=self.store_id,
                external_product_id="123:456",
                url=product_url,
                price="89.90",
                currency="EUR",
                availability="in_stock",
                source="test",
                status="active",
            ))

        class ShopifyRefreshConnector(FakeLegacyConnector):
            store_key = "orioudh"

            async def fetch_offer_price_and_stock(self, external_id, persisted_url=None):
                return {"raw_record": {"price": "88.90"}, "captured_at": 1}

            def parse_raw(self, raw):
                return {
                    "price": "88.90",
                    "currency": "EUR",
                    "currency_explicit": True,
                    "currency_source": "untrusted_product_json_default",
                    "availability": "in_stock",
                    "product_url": product_url,
                    "url": product_url,
                    "source": "test",
                }

        connector = ShopifyRefreshConnector()
        with (
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(legacy_runtime, "connector_key_for_store_slug", return_value="orioudh"),
            patch.object(legacy_runtime, "build_legacy_connector", return_value=connector),
            patch.object(legacy_runtime, "refresh_offer_observation") as refresh,
        ):
            with self.assertRaisesRegex(ValueError, "shopify_currency_provenance"):
                legacy_runtime.handle_legacy_refresh({
                    "store_id": str(self.store_id),
                    "external_product_id": "123:456",
                })

        refresh.assert_not_called()

    def test_legacy_refresh_rejects_missing_offer_before_network(self):
        class MustNotFetch(FakeLegacyConnector):
            async def fetch_offer_price_and_stock(self, external_id, persisted_url=None):
                raise AssertionError("network refresh must not run without an active offer")

        with (
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(legacy_runtime, "build_legacy_connector", return_value=MustNotFetch()),
        ):
            with self.assertRaisesRegex(LookupError, "active_offer_not_found"):
                legacy_runtime.handle_legacy_refresh({
                    "store_id": str(self.store_id),
                    "external_product_id": "missing",
                })


if __name__ == "__main__":
    unittest.main()

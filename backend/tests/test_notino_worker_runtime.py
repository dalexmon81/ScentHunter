from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, IngestionRun, Store
from app.connectors.base import ConnectorUnavailable, DiscoveredProduct
from app.services.connector_ingestion import ConnectorIngestionResult
from app.workers import notino_runtime
from app.workers.runtime import clear_handlers, get_handler


class FakeNotinoConnector:
    async def discover_products(self, *, cursor=None, limit=100):
        return (
            DiscoveredProduct(
                external_product_id="CJ-123",
                product_url="https://www.notino.fr/product/cj-123",
                raw_payload={"external_product_id": "CJ-123"},
            ),
        )

    async def fetch_product(self, external_product_id):
        if external_product_id != "CJ-123":
            return None
        return {
            "external_product_id": "CJ-123",
            "title": "Dior Sauvage Eau de Parfum 100 ml",
            "price": "89.90",
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "product_url": "https://www.notino.fr/product/cj-123",
            "url": "https://www.notino.fr/product/cj-123",
        }


class NotinoWorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as session, session.begin():
            self.store = Store(
                name="Notino.fr",
                slug="notino-fr",
                domain="notino.fr",
                country="FR",
                currency="EUR",
                status="active",
            )
            session.add(self.store)
            session.flush()
            self.store_id = self.store.id
        self.patches = [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(notino_runtime, "_connector", return_value=FakeNotinoConnector()),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        clear_handlers()
        self.engine.dispose()

    def test_candidate_filter_uses_canonical_database_matcher(self):
        connector = FakeNotinoConnector()
        parsed = {
            "external_product_id": "CJ-123",
            "raw_name": "Dior Sauvage Eau de Parfum 100 ml",
            "brand_raw": "Dior",
            "size_ml": 100,
            "concentration": "Eau de Parfum",
            "currency_explicit": True,
        }
        connector.parse_raw = lambda raw: parsed
        connector.validate_offer = lambda raw: SimpleNamespace(valid=True, errors=())
        match = SimpleNamespace(product_variant_id=uuid4())
        with patch.object(
            notino_runtime, "resolve_canonical_variant",
            return_value=SimpleNamespace(match=match, reason="matched"),
        ) as resolve:
            self.assertTrue(notino_runtime._is_unique_canonical_candidate(
                connector, self.store_id, {"external_product_id": "CJ-123"}
            ))
        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.kwargs["store_id"], self.store_id)
        self.assertEqual(resolve.call_args.kwargs["external_product_id"], "CJ-123")
        self.assertEqual(resolve.call_args.kwargs["record"]["brand_raw"], "Dior")

    def test_candidate_filter_rejects_unmatched_canonical_record(self):
        connector = FakeNotinoConnector()
        connector.parse_raw = lambda raw: {
            "external_product_id": "CJ-404",
            "currency_explicit": True,
        }
        connector.validate_offer = lambda raw: SimpleNamespace(valid=True, errors=())
        with patch.object(
            notino_runtime, "resolve_canonical_variant",
            return_value=SimpleNamespace(match=None, reason="no_canonical_variant_match"),
        ):
            self.assertFalse(notino_runtime._is_unique_canonical_candidate(
                connector, self.store_id, {"external_product_id": "CJ-404"}
            ))

    def test_discovery_queues_products_and_records_run(self):
        with patch.object(notino_runtime, "_is_unique_canonical_candidate", return_value=True), \
             patch.object(notino_runtime, "enqueue_offer_fetch") as enqueue_fetch:
            result = notino_runtime.handle_notino_discovery({
                "store_id": str(self.store_id),
                "limit": 10,
            })
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["products_discovered"], 1)
        self.assertEqual(result["canonical_candidates"], 1)
        self.assertEqual(result["canonical_candidates_skipped"], 0)
        self.assertEqual(result["fetch_jobs_queued"], 1)
        enqueue_fetch.assert_called_once_with(self.store_id, "CJ-123")
        with self.sessions() as session:
            run = session.get(IngestionRun, __import__("uuid").UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.products_discovered, 1)

    def test_discovery_skips_noncanonical_candidates(self):
        with patch.object(notino_runtime, "_is_unique_canonical_candidate", return_value=False), \
             patch.object(notino_runtime, "enqueue_offer_fetch") as enqueue_fetch:
            result = notino_runtime.handle_notino_discovery({
                "store_id": str(self.store_id),
                "limit": 10,
            })
        self.assertEqual(result["canonical_candidates"], 0)
        self.assertEqual(result["canonical_candidates_skipped"], 1)
        self.assertEqual(result["fetch_jobs_queued"], 0)
        enqueue_fetch.assert_not_called()

    def test_fetch_persists_result_and_tracks_created_offer(self):
        fake_result = ConnectorIngestionResult(
            ingestion_raw_id=uuid4(),
            status="promoted",
            offer_id=uuid4(),
            product_variant_id=uuid4(),
        )
        with patch.object(notino_runtime, "persist_connector_record", return_value=fake_result):
            result = notino_runtime.handle_notino_fetch({
                "store_id": str(self.store_id),
                "external_product_id": "CJ-123",
            })
        self.assertEqual(result["status"], "promoted")
        with self.sessions() as session:
            run = session.get(IngestionRun, __import__("uuid").UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.products_discovered, 1)
            self.assertEqual(run.offers_created, 1)
            self.assertEqual(run.offers_rejected, 0)

    def test_unknown_store_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "active notino-fr"):
            notino_runtime.handle_notino_discovery({
                "store_id": str(uuid4()),
                "limit": 10,
            })

    def test_feed_outage_updates_connector_health_without_publishing(self):
        class BrokenConnector(FakeNotinoConnector):
            async def discover_products(self, *, cursor=None, limit=100):
                raise ConnectorUnavailable("feed timeout")

        with patch.object(notino_runtime, "_connector", return_value=BrokenConnector()):
            with self.assertRaisesRegex(ConnectorUnavailable, "feed timeout"):
                notino_runtime.handle_notino_discovery({
                    "store_id": str(self.store_id),
                    "limit": 10,
                })
        with self.sessions() as session:
            store = session.get(Store, self.store_id)
            self.assertEqual(store.consecutive_failures, 1)
            self.assertEqual(store.last_connector_error, "feed timeout")
            self.assertEqual(store.status, "active")

    def test_worker_bootstrap_registers_notino_discovery_and_fetch(self):
        notino_runtime.register_notino_handlers()
        self.assertIs(get_handler("discover"), notino_runtime.handle_notino_discovery)
        self.assertIs(get_handler("fetch"), notino_runtime.handle_notino_fetch)
        self.assertIs(get_handler("refresh"), notino_runtime.handle_notino_refresh)


if __name__ == "__main__":
    unittest.main()

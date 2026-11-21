from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.connectors.base import DiscoveredProduct
from app.models import Base, IngestionRun, Offer, Store
from app.services.connector_ingestion import ConnectorIngestionResult
from app.workers import bplatz_runtime, legacy_runtime, notino_runtime


class FakeBplatzConnector:
    store_key = "bplatz"

    async def discover_products(self, *, cursor=None, limit=100):
        return (
            DiscoveredProduct(
                external_product_id="https://en.bplatz.de/products/liquid-brun",
                product_url="https://en.bplatz.de/products/liquid-brun",
                raw_payload={"url": "https://en.bplatz.de/products/liquid-brun"},
            ),
        )

    async def fetch_product(self, external_product_id):
        return {
            "external_product_id": external_product_id,
            "name": "French Avenue Liquid Brun Eau de Parfum 100 ml",
            "url": external_product_id,
            "price_num": 27.5,
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
        }

    async def fetch_offer_price_and_stock(self, offer_id, product_url=None):
        return {
            "raw_record": {"price": "26.90"},
            "captured_at": 1,
        }

    def parse_raw(self, raw):
        return {
            "external_product_id": raw.get("external_product_id", "https://en.bplatz.de/products/liquid-brun"),
            "price": str(raw.get("price", "26.90")),
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "product_url": "https://en.bplatz.de/products/liquid-brun",
            "url": "https://en.bplatz.de/products/liquid-brun",
            "source": "bplatz_scraper",
        }

    def validate_offer(self, parsed):
        return SimpleNamespace(valid=True, errors=())


class BplatzWorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as session, session.begin():
            store = Store(
                name="Bplatz", slug="bplatz", domain="bplatz.de",
                country="DE", currency="EUR", status="active",
            )
            session.add(store)
            session.flush()
            self.store_id = store.id

    def tearDown(self):
        self.engine.dispose()

    def _common_patches(self, connector=None):
        return [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(notino_runtime, "_matcher", return_value=object()),
            patch.object(bplatz_runtime, "build_bplatz_connector", return_value=connector or FakeBplatzConnector()),
        ]

    def test_discovery_queues_only_canonical_candidates(self):
        patches = self._common_patches()
        patches.append(patch.object(bplatz_runtime, "enqueue_offer_fetch"))
        started = [item.start() for item in patches]
        enqueue_fetch = started[-1]
        try:
            result = bplatz_runtime.handle_bplatz_discovery({
                "store_id": str(self.store_id), "limit": 10,
            })
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["store"], "bplatz")
        self.assertEqual(result["products_discovered"], 1)
        self.assertEqual(result["fetch_jobs_queued"], 1)
        enqueue_fetch.assert_called_once_with(
            self.store_id, "https://en.bplatz.de/products/liquid-brun"
        )
        with self.sessions() as session:
            run = session.get(IngestionRun, UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.products_discovered, 1)

    def test_generic_dispatch_routes_bplatz_to_its_isolated_runtime(self):
        with (
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(bplatz_runtime, "handle_bplatz_discovery", return_value={"status": "routed"}) as handler,
        ):
            result = legacy_runtime._dispatch("discover", {"store_id": str(self.store_id)})
        self.assertEqual(result, {"status": "routed"})
        handler.assert_called_once_with({"store_id": str(self.store_id)})

    def test_discovery_rejects_inactive_or_non_bplatz_store(self):
        with self.sessions() as session, session.begin():
            store = Store(
                name="Deloox", slug="deloox-be", domain="www.deloox.be",
                country="BE", currency="EUR", status="active",
            )
            session.add(store)
            session.flush()
            other_id = store.id
        with patch.object(notino_runtime, "_sessions", return_value=self.sessions):
            with self.assertRaisesRegex(ValueError, "active bplatz"):
                bplatz_runtime.handle_bplatz_discovery({"store_id": str(other_id)})

    def test_fetch_uses_shared_catalog_persistence_gate(self):
        fake_result = ConnectorIngestionResult(
            ingestion_raw_id=uuid4(), status="promoted",
            offer_id=uuid4(), product_variant_id=uuid4(),
        )
        patches = self._common_patches()
        patches.append(patch.object(bplatz_runtime, "persist_connector_record", return_value=fake_result))
        started = [item.start() for item in patches]
        persist = started[-1]
        try:
            result = bplatz_runtime.handle_bplatz_fetch({
                "store_id": str(self.store_id),
                "external_product_id": "https://en.bplatz.de/products/liquid-brun",
            })
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["store"], "bplatz")
        persist.assert_called_once()
        with self.sessions() as session:
            run = session.get(IngestionRun, UUID(result["run_id"]))
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.offers_created, 1)

    def test_refresh_uses_existing_offer_and_shared_history_service(self):
        product_url = "https://en.bplatz.de/products/liquid-brun"
        with self.sessions() as session, session.begin():
            session.add(Offer(
                store_id=self.store_id,
                external_product_id=product_url,
                url=product_url,
                price="27.50",
                currency="EUR",
                availability="in_stock",
                source="test",
                status="active",
            ))
        patches = self._common_patches()
        patches.append(patch.object(bplatz_runtime, "refresh_offer_observation"))
        started = [item.start() for item in patches]
        refresh = started[-1]
        try:
            result = bplatz_runtime.handle_bplatz_refresh({
                "store_id": str(self.store_id),
                "external_product_id": product_url,
            })
        finally:
            for item in reversed(patches):
                item.stop()
        self.assertEqual(result["status"], "refreshed")
        refresh.assert_called_once()
        self.assertEqual(refresh.call_args.kwargs["currency_explicit"], True)

    def test_refresh_does_not_fetch_when_offer_is_missing(self):
        connector = FakeBplatzConnector()

        class MustNotFetch(FakeBplatzConnector):
            async def fetch_offer_price_and_stock(self, offer_id, product_url=None):
                raise AssertionError("refresh must not fetch without a persisted offer")

        patches = [
            patch.object(notino_runtime, "_sessions", return_value=self.sessions),
            patch.object(bplatz_runtime, "build_bplatz_connector", return_value=MustNotFetch()),
        ]
        for item in patches:
            item.start()
        try:
            with self.assertRaisesRegex(LookupError, "active_bplatz_offer_not_found"):
                bplatz_runtime.handle_bplatz_refresh({
                    "store_id": str(self.store_id),
                    "external_product_id": "https://en.bplatz.de/products/missing",
                })
        finally:
            for item in reversed(patches):
                item.stop()


if __name__ == "__main__":
    unittest.main()

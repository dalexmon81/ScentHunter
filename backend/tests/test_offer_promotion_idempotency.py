from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Base, Brand, Fragrance, MatchAudit, Offer, PriceHistory,
    ProductVariant, Store,
)
from app.services.ingestion_persistence import (
    PromotionRejected, promote_offer, record_match, stage_raw_offer,
)


class OfferPromotionIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        database_url = os.environ.get("SCENTHUNTER_TEST_POSTGRES_URL", "sqlite:///:memory:")
        self.engine = create_engine(database_url)
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        Base.metadata.create_all(self.connection)
        self.session = Session(bind=self.connection)
        suffix = uuid4().hex[:12]
        store = Store(
            name="Fixture retailer", slug=f"fixture-retailer-{suffix}",
            currency="EUR", status="active",
        )
        brand = Brand(name="Dior", slug=f"dior-{suffix}", normalized_name=f"dior-{suffix}")
        self.session.add_all([store, brand])
        self.session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug=f"sauvage-{suffix}")
        self.session.add(fragrance)
        self.session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
            canonical_key=f"dior|sauvage|edp|100|{suffix}",
        )
        self.session.add(variant)
        self.session.flush()
        self.store_id = store.id
        self.variant_id = variant.id
        second_variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="EDT", size_ml=100,
            canonical_key=f"dior|sauvage|edt|100|{suffix}",
        )
        self.session.add(second_variant)
        self.session.flush()
        self.second_variant_id = second_variant.id

    def tearDown(self) -> None:
        self.session.close()
        if self.transaction.is_active:
            self.transaction.rollback()
        self.connection.close()
        self.engine.dispose()

    def _promote_snapshot(self, price: str):
        raw_id = stage_raw_offer(
            self.session, store_id=self.store_id,
            external_product_id="retailer-item-123",
            raw_payload={"price": price},
        )
        record_match(
            self.session, ingestion_raw_id=raw_id,
            product_variant_id=self.variant_id,
            method="test_exact_match",
        )
        return promote_offer(
            self.session, ingestion_raw_id=raw_id,
            price=Decimal(price), currency="EUR",
            url="https://retailer.example/item/123",
            availability="in_stock", source="fixture",
        )

    def test_external_retailer_identity_cannot_be_reassigned_to_another_variant(self):
        first_id = self._promote_snapshot("89.90")
        raw_id = stage_raw_offer(
            self.session, store_id=self.store_id,
            external_product_id="retailer-item-123",
            raw_payload={"price": "79.90"},
        )
        record_match(
            self.session, ingestion_raw_id=raw_id,
            product_variant_id=self.second_variant_id,
            method="test_conflicting_match",
        )
        with self.assertRaisesRegex(
            PromotionRejected, "already linked to a different canonical variant"
        ):
            promote_offer(
                self.session, ingestion_raw_id=raw_id,
                price=Decimal("79.90"), currency="EUR",
                url="https://retailer.example/item/123",
                availability="in_stock", source="fixture",
            )
        self.session.flush()
        offer = self.session.get(Offer, first_id)
        self.assertEqual(offer.product_variant_id, self.variant_id)
        self.assertEqual(offer.price, Decimal("89.90"))
        self.assertEqual(self.session.scalar(
            select(Offer.id).where(
                Offer.store_id == self.store_id,
                Offer.external_product_id == "retailer-item-123",
            )
        ), first_id)

    def test_concurrent_promotions_for_same_retailer_identity_are_serialized(self):
        if self.engine.dialect.name != "postgresql":
            self.skipTest("row-lock concurrency guarantee is PostgreSQL-specific")

        # Publish fixture rows so independent worker sessions can see them.
        self.session.commit()
        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        raw_ids = []
        for price in ("69.90", "59.90"):
            with factory() as session:
                raw_id = stage_raw_offer(
                    session, store_id=self.store_id,
                    external_product_id="concurrent-retailer-item",
                    raw_payload={"price": price},
                )
                record_match(
                    session, ingestion_raw_id=raw_id,
                    product_variant_id=self.variant_id,
                    method="test_concurrent_exact_match",
                )
                session.commit()
                raw_ids.append((raw_id, price))

        barrier = Barrier(2)

        def promote(item):
            raw_id, price = item
            with factory() as session:
                barrier.wait(timeout=10)
                offer_id = promote_offer(
                    session, ingestion_raw_id=raw_id,
                    price=Decimal(price), currency="EUR",
                    url="https://retailer.example/concurrent",
                    availability="in_stock", source="concurrency-fixture",
                )
                session.commit()
                return offer_id

        with ThreadPoolExecutor(max_workers=2) as pool:
            offer_ids = list(pool.map(promote, raw_ids))

        self.assertEqual(offer_ids[0], offer_ids[1])
        with factory() as session:
            offers = session.scalars(select(Offer).where(
                Offer.store_id == self.store_id,
                Offer.external_product_id == "concurrent-retailer-item",
            )).all()
            history = session.scalars(select(PriceHistory).where(
                PriceHistory.offer_id == offer_ids[0]
            )).all()
            self.assertEqual(len(offers), 1)
            self.assertEqual(len(history), 2)

    def test_repeated_snapshots_update_one_offer_and_preserve_history(self):
        first_id = self._promote_snapshot("89.90")
        second_id = self._promote_snapshot("79.90")
        self.session.commit()

        offers = self.session.scalars(select(Offer).where(
            Offer.store_id == self.store_id
        )).all()
        history = self.session.scalars(select(PriceHistory).where(
            PriceHistory.offer_id == first_id
        )).all()
        audits = self.session.scalars(select(MatchAudit).where(
            MatchAudit.offer_id == first_id
        )).all()

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, Decimal("79.90"))
        self.assertEqual(offers[0].external_product_id, "retailer-item-123")
        self.assertEqual(sorted(row.price for row in history), [
            Decimal("79.90"), Decimal("89.90")
        ])
        self.assertEqual(len(audits), 2)


if __name__ == "__main__":
    unittest.main()

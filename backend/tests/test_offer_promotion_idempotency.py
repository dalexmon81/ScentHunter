from __future__ import annotations

import unittest
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Base, Brand, Fragrance, MatchAudit, Offer, PriceHistory,
    ProductVariant, Store,
)
from app.services.ingestion_persistence import (
    promote_offer, record_match, stage_raw_offer,
)


class OfferPromotionIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        store = Store(
            name="Fixture retailer", slug="fixture-retailer",
            currency="EUR", status="active",
        )
        brand = Brand(name="Dior", slug="dior", normalized_name="dior")
        self.session.add_all([store, brand])
        self.session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug="sauvage")
        self.session.add(fragrance)
        self.session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
            canonical_key="dior|sauvage|edp|100",
        )
        self.session.add(variant)
        self.session.flush()
        self.store_id = store.id
        self.variant_id = variant.id

    def tearDown(self) -> None:
        self.session.close()
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

    def test_repeated_snapshots_update_one_offer_and_preserve_history(self):
        first_id = self._promote_snapshot("89.90")
        second_id = self._promote_snapshot("79.90")
        self.session.commit()

        offers = self.session.scalars(select(Offer)).all()
        history = self.session.scalars(select(PriceHistory).order_by(
            PriceHistory.captured_at, PriceHistory.id
        )).all()
        audits = self.session.scalars(select(MatchAudit)).all()

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, Decimal("79.90"))
        self.assertEqual(offers[0].external_product_id, "retailer-item-123")
        self.assertEqual([row.price for row in history], [
            Decimal("89.90"), Decimal("79.90")
        ])
        self.assertEqual(len(audits), 2)


if __name__ == "__main__":
    unittest.main()

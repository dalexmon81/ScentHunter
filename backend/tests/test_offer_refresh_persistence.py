from __future__ import annotations

import unittest
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, Brand, Fragrance, Offer, PriceHistory, ProductVariant, Store, IngestionRaw
from app.services.offer_refresh import refresh_offer_observation


class OfferRefreshPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions() as session, session.begin():
            store = Store(name="Notino.fr", slug="notino-fr", country="FR", currency="EUR", status="active")
            brand = Brand(name="Dior", slug="dior", normalized_name="dior")
            session.add_all([store, brand])
            session.flush()
            fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug="sauvage")
            session.add(fragrance)
            session.flush()
            variant = ProductVariant(fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
                                     canonical_key="dior|sauvage|edp|100")
            session.add(variant)
            session.flush()
            offer = Offer(store_id=store.id, product_variant_id=variant.id,
                          external_product_id="CJ-123", url="https://www.notino.fr/p/123",
                          price=Decimal("89.90"), currency="EUR", availability="in_stock",
                          source="cj_feed", status="active")
            session.add(offer)
            session.flush()
            self.offer_id = offer.id

    def tearDown(self):
        self.engine.dispose()

    def test_refresh_updates_current_offer_and_appends_history(self):
        with self.sessions() as session, session.begin():
            result = refresh_offer_observation(
                session, offer_id=self.offer_id,
                observation={"price": "79.90", "currency": "EUR",
                             "availability": "out_of_stock",
                             "product_url": "https://www.notino.fr/p/123"},
                source="authorized_cj_feed",
            )
            self.assertEqual(result, self.offer_id)
        with self.sessions() as session:
            offer = session.get(Offer, self.offer_id)
            history = session.scalars(select(PriceHistory).where(
                PriceHistory.offer_id == self.offer_id
            )).all()
            raw = session.scalar(select(IngestionRaw).where(
                IngestionRaw.id == offer.ingestion_raw_id
            ))
            self.assertEqual(offer.price, Decimal("79.90"))
            self.assertEqual(offer.availability, "out_of_stock")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].price, Decimal("79.90"))
            self.assertEqual(raw.status, "promoted")

    def test_refresh_rejects_missing_or_ambiguous_stock(self):
        with self.sessions() as session, session.begin():
            with self.assertRaisesRegex(ValueError, "availability must be explicit"):
                refresh_offer_observation(
                    session, offer_id=self.offer_id,
                    observation={"price": "79.90", "currency": "EUR",
                                 "availability": "unknown"},
                    source="authorized_cj_feed",
                )

    def test_refresh_rejects_currency_change_for_manual_review(self):
        with self.sessions() as session, session.begin():
            with self.assertRaisesRegex(ValueError, "currency changed"):
                refresh_offer_observation(
                    session, offer_id=self.offer_id,
                    observation={"price": "79.90", "currency": "USD",
                                 "availability": "in_stock"},
                    source="authorized_cj_feed",
                )


if __name__ == "__main__":
    unittest.main()

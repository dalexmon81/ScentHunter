"""Real PostgreSQL integration test for Offer Engine persistence and FK integrity."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - exercised only in the CI PostgreSQL job
    psycopg = None

from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.repository import OfferRepository
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


@unittest.skipUnless(psycopg is not None and os.getenv("SCENTHUNTER_TEST_POSTGRES_DSN"), "PostgreSQL integration DSN not configured")
class OfferEnginePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.connection = psycopg.connect(os.environ["SCENTHUNTER_TEST_POSTGRES_DSN"])
        migration = (root / "backend" / "offer_engine" / "migrations" / "001_offer_engine.sql").read_text()
        with cls.connection.cursor() as cursor:
            cursor.execute(migration)
        cls.connection.commit()
        cls.catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "connection", None):
            cls.connection.close()

    def test_verified_listing_and_current_offer_obey_real_foreign_keys(self):
        product = self.catalog.get("SH-0031")
        self.assertIsNotNone(product)
        variant = next(v for v in product.variants if v.variant_id == "VAR-f5aff76b4bb5de8a")
        self.assertEqual(variant.size_ml, 150)
        url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
        listing = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun Extrait de Parfum Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, raw_gtin="6298042001831", market="BE",
        )
        observation = OfferObservation(
            listing_key="deloox:1385920", observed_at=datetime.now(timezone.utc),
            price=None, currency="EUR", availability=Availability.OUT_OF_STOCK,
            source="product_page", verification=Verification.VERIFIED,
            product_id=product.product_id, variant_id=variant.variant_id,
            evidence_url=url, evidence_hash="sha256:postgres-integration",
        )
        result = OfferRepository(self.connection, canonical_catalog=self.catalog).record(listing, observation)
        self.assertFalse(result["published"])
        self.assertEqual(result["policy_reason"], "price_missing")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT product_id, variant_id FROM sh_current_offers WHERE listing_id=%s", (result["listing_id"],))
            self.assertIsNone(cursor.fetchone())
            cursor.execute("SELECT canonical_product_id, canonical_variant_id, match_status FROM sh_retailer_listings WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone(), (product.product_id, variant.variant_id, "matched"))
            cursor.execute("SELECT count(*) FROM sh_offer_observations WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT availability, price, verification FROM sh_offer_observations WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone(), ("out_of_stock", None, "verified"))


if __name__ == "__main__":
    unittest.main()

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
from backend.offer_engine.read_repository import OfferReadRepository
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


@unittest.skipUnless(psycopg is not None and os.getenv("SCENTHUNTER_TEST_POSTGRES_DSN"), "PostgreSQL integration DSN not configured")
class OfferEnginePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.connection = psycopg.connect(os.environ["SCENTHUNTER_TEST_POSTGRES_DSN"])
        migration_dir = root / "backend" / "offer_engine" / "migrations"
        with cls.connection.cursor() as cursor:
            for migration_path in sorted(migration_dir.glob("*.sql")):
                cursor.execute(migration_path.read_text(encoding="utf-8"))
        cls.connection.commit()
        cls.catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "connection", None):
            cls.connection.close()

    def test_distinct_feed_variants_can_share_one_product_url(self):
        url = "https://www.notino.fr/french-avenue/liquid-brun/"
        repository = OfferRepository(self.connection, canonical_catalog=self.catalog)
        listing_ids = []
        for external_id, size in (("LB100", 100), ("LB150", 150)):
            listing = RetailerListing(
                retailer="notino", external_id=external_id, product_url=url,
                raw_title=f"French Avenue Liquid Brun {size} ml",
                raw_brand="French Avenue", raw_size_ml=size, market="FR",
            )
            observation = OfferObservation.now(
                listing_key=f"notino:{external_id}", price=None, currency="EUR",
                availability=Availability.UNKNOWN, source="feed",
                verification=Verification.UNVERIFIED,
                evidence_url=url, evidence_hash=f"sha256:{external_id}",
            )
            result = repository.record(listing, observation)
            listing_ids.append(result["listing_id"])
        self.assertEqual(len(set(listing_ids)), 2)
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM sh_retailer_listings WHERE retailer_id=%s AND product_url=%s",
                ("notino", url),
            )
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_multiple_feed_variants_can_share_one_product_url(self):
        url = "https://www.notino.fr/example-product.html"
        with self.connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sh_retailers(retailer_id, display_name, market) VALUES ('notino', 'Notino', 'FR') ON CONFLICT DO NOTHING"
            )
            for external_id, size in (("notino-100", 100), ("notino-150", 150)):
                cursor.execute(
                    """INSERT INTO sh_retailer_listings
                       (retailer_id, external_id, product_url, market, raw_title, raw_size_ml, match_status)
                       VALUES ('notino', %s, %s, 'FR', 'French Avenue Liquid Brun', %s, 'unresolved')""",
                    (external_id, url, size),
                )
            cursor.execute(
                "SELECT count(*) FROM sh_retailer_listings WHERE retailer_id='notino' AND product_url=%s",
                (url,),
            )
            self.assertEqual(cursor.fetchone()[0], 2)
        self.connection.commit()

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
        self.assertTrue(result["published"])
        self.assertEqual(result["policy_reason"], "verified_out_of_stock")
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT product_id, variant_id FROM sh_current_offers WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone(), (product.product_id, variant.variant_id))
            cursor.execute("SELECT canonical_product_id, canonical_variant_id, match_status FROM sh_retailer_listings WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone(), (product.product_id, variant.variant_id, "matched"))
            cursor.execute("SELECT count(*) FROM sh_offer_observations WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute("SELECT availability, price, verification FROM sh_offer_observations WHERE listing_id=%s", (result["listing_id"],))
            self.assertEqual(cursor.fetchone(), ("out_of_stock", None, "verified"))
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO sh_offer_observations
                       (listing_id, observed_at, price, currency, availability, source, verification, raw_payload)
                       VALUES (%s,%s,%s,%s,'out_of_stock','product_page','unverified','{}'::jsonb)""",
                    (result["listing_id"], datetime.now(timezone.utc), Decimal("10.00"), "EUR"),
                )
        self.connection.rollback()
        current = OfferReadRepository(self.connection).search("Liquid Brun", market="BE")
        sold_out = next(
            row for row in current
            if row["product_id"] == product.product_id
            and row["variant_id"] == variant.variant_id
        )
        self.assertEqual(sold_out["availability"], "out_of_stock")
        self.assertIsNone(sold_out["price"])
        self.assertEqual(sold_out["size_ml"], 150)
        with self.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE sh_current_offers SET verified_at=now() - interval '3 days' WHERE listing_id=%s",
                (result["listing_id"],),
            )
        self.connection.commit()
        self.assertEqual(OfferReadRepository(self.connection).search("Liquid Brun", market="BE"), [])


if __name__ == "__main__":
    unittest.main()

"""SQLite integration coverage for the isolated Offer Engine Fly-volume backend."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.repository import OfferRepository
from backend.offer_engine.read_repository import OfferReadRepository
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


class OfferEngineSQLiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        cls.catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        cls.migration = (root / "backend" / "offer_engine" / "migrations" / "001_offer_engine_sqlite.sql").read_text(encoding="utf-8")

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(self.migration)

    def tearDown(self):
        self.connection.close()

    def test_verified_sold_out_150ml_is_current_without_price(self):
        product = self.catalog.get("SH-0031")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        url = "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-limited-edition-150-ml.html"
        listing = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150,
            raw_gtin="6298042001831", market="BE",
        )
        observation = OfferObservation(
            listing_key="deloox:1385920",
            observed_at=datetime.now(timezone.utc),
            price=None, currency="EUR", availability=Availability.OUT_OF_STOCK,
            source="product_page", verification=Verification.VERIFIED,
            product_id=product.product_id, variant_id=variant.variant_id,
            evidence_url=url, evidence_hash="sha256:sqlite-sold-out",
        )
        result = OfferRepository(self.connection, canonical_catalog=self.catalog).record(listing, observation)
        self.assertTrue(result["published"])
        self.assertEqual(result["policy_reason"], "verified_out_of_stock")
        offers = OfferReadRepository(self.connection).search("Liquid Brun", market="BE")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["variant_id"], variant.variant_id)
        self.assertEqual(offers[0]["size_ml"], 150)
        self.assertEqual(offers[0]["availability"], "out_of_stock")
        self.assertIsNone(offers[0]["price"])

    def test_unresolved_rematch_clears_old_identity_and_current_price(self):
        product = self.catalog.get("SH-0031")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        url = "https://www.deloox.be/produit/1385920/liquid-brun-limited-150.html"
        listing = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="BE",
        )
        repository = OfferRepository(self.connection, canonical_catalog=self.catalog)
        verified = OfferObservation.now(
            listing_key="deloox:1385920", price=__import__("decimal").Decimal("42.89"),
            currency="EUR", availability=Availability.IN_STOCK, source="product_page",
            verification=Verification.VERIFIED, product_id=product.product_id,
            variant_id=variant.variant_id, evidence_url=url, evidence_hash="sha256:verified",
        )
        first = repository.record(listing, verified)
        self.assertTrue(first["published"])
        unresolved = OfferObservation.now(
            listing_key="deloox:1385920", price=None, currency="EUR",
            availability=Availability.UNKNOWN, source="product_page",
            verification=Verification.UNVERIFIED, evidence_url=url,
            evidence_hash="sha256:ambiguous-rematch",
        )
        repository.record(listing, unresolved, match_status="ambiguous")
        row = self.connection.execute(
            "SELECT canonical_product_id, canonical_variant_id, match_status "
            "FROM sh_retailer_listings WHERE retailer_id='deloox' AND external_id='1385920'"
        ).fetchone()
        self.assertEqual(tuple(row), (None, None, "ambiguous"))
        self.assertEqual(
            self.connection.execute("SELECT count(*) FROM sh_current_offers").fetchone()[0],
            0,
        )
        self.assertEqual(OfferReadRepository(self.connection).search("Liquid Brun", market="BE"), [])

    def test_two_variant_ids_can_share_one_parent_product_url(self):
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
            listing_ids.append(repository.record(listing, observation)["listing_id"])
        self.assertEqual(len(set(listing_ids)), 2)
        count = self.connection.execute(
            "SELECT count(*) FROM sh_retailer_listings WHERE retailer_id=? AND product_url=?",
            ("notino", url),
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_stale_verified_offer_is_hidden_from_read_model(self):
        product = self.catalog.get("SH-0031")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        url = "https://www.deloox.be/produit/1385920/liquid-brun-limited-150.html"
        listing = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="BE",
        )
        observation = OfferObservation(
            listing_key="deloox:1385920", observed_at=datetime.now(timezone.utc),
            price=None, currency="EUR", availability=Availability.OUT_OF_STOCK,
            source="product_page", verification=Verification.VERIFIED,
            product_id=product.product_id, variant_id=variant.variant_id,
            evidence_url=url, evidence_hash="sha256:stale",
        )
        result = OfferRepository(self.connection, canonical_catalog=self.catalog).record(listing, observation)
        self.connection.execute(
            "UPDATE sh_current_offers SET verified_at='2000-01-01 00:00:00' WHERE listing_id=?",
            (result["listing_id"],),
        )
        self.connection.commit()
        self.assertEqual(OfferReadRepository(self.connection).search("Liquid Brun", market="BE"), [])


if __name__ == "__main__":
    unittest.main()

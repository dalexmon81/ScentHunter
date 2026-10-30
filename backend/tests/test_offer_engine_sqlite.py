"""SQLite integration coverage for the isolated Offer Engine Fly-volume backend."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_read_model_deduplicates_same_retailer_variant_market_by_best_price(self):
        product = self.catalog.get("SH-0030")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f87146c82d167f4c")
        repository = OfferRepository(self.connection, canonical_catalog=self.catalog)
        listings = [
            RetailerListing(
                retailer="parfumzentrum", external_id="duplicate-a",
                product_url="https://www.parfumzentrum.de/liquid-brun-a.html",
                raw_title="French Avenue Liquid Brun Eau de Parfum 100 ml",
                raw_brand="French Avenue", raw_size_ml=100, market="DE",
            ),
            RetailerListing(
                retailer="parfumzentrum", external_id="duplicate-b",
                product_url="https://www.parfumzentrum.de/liquid-brun-b.html",
                raw_title="French Avenue Liquid Brun Eau de Parfum 100 ml",
                raw_brand="French Avenue", raw_size_ml=100, market="DE",
            ),
        ]
        for index, (listing, price) in enumerate(zip(listings, (Decimal("45.00"), Decimal("39.99")))):
            repository.record(
                listing,
                OfferObservation.now(
                    listing_key=f"parfumzentrum:{listing.external_id}",
                    price=price, currency="EUR", availability=Availability.IN_STOCK,
                    source="product_page", verification=Verification.VERIFIED,
                    product_id=product.product_id, variant_id=variant.variant_id,
                    evidence_url=listing.product_url, evidence_hash=f"sha256:duplicate-{index}",
                ),
            )

        offers = OfferReadRepository(self.connection).search("Liquid Brun", market="DE")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["variant_id"], variant.variant_id)
        self.assertEqual(str(offers[0]["price"]), "39.99")
        self.assertEqual(offers[0]["product_url"], listings[1].product_url)

    def test_shopify_offer_link_targets_the_exact_variant(self):
        product = self.catalog.get("SH-0031")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        base_url = "https://www.parfumcity.nl/products/liquid-brun-limited-edition-french-avenue-100-ml"
        listing = RetailerListing(
            retailer="parfumcity", external_id="1234567890123",
            product_url=base_url, raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="NL",
        )
        OfferRepository(self.connection, canonical_catalog=self.catalog).record(
            listing,
            OfferObservation.now(
                listing_key="parfumcity:1234567890123",
                price=Decimal("39.99"), currency="EUR", availability=Availability.IN_STOCK,
                source="product_page", verification=Verification.VERIFIED,
                product_id=product.product_id, variant_id=variant.variant_id,
                evidence_url=base_url, evidence_hash="sha256:shopify-variant-link",
            ),
        )
        offers = OfferReadRepository(self.connection).search("Liquid Brun", market="NL")
        self.assertEqual(len(offers), 1)
        self.assertEqual(
            offers[0]["product_url"],
            base_url + "?variant=1234567890123",
        )

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

    def test_stale_verified_identity_change_cannot_replace_newer_current_offer(self):
        repository = OfferRepository(self.connection, canonical_catalog=self.catalog)
        product_150 = self.catalog.get("SH-0031")
        variant_150 = next(item for item in product_150.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        product_100 = self.catalog.get("SH-0030")
        variant_100 = next(item for item in product_100.variants if item.variant_id == "VAR-f87146c82d167f4c")
        url = "https://www.deloox.be/produit/1385920/liquid-brun.html"
        listing_150 = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="BE",
        )
        newer = OfferObservation.now(
            listing_key="deloox:1385920", price=__import__("decimal").Decimal("42.89"),
            currency="EUR", availability=Availability.IN_STOCK, source="product_page",
            verification=Verification.VERIFIED, product_id=product_150.product_id,
            variant_id=variant_150.variant_id, evidence_url=url, evidence_hash="sha256:newer",
        )
        first = repository.record(listing_150, newer)
        self.assertTrue(first["published"])

        older_listing = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun 100 ml",
            raw_brand="French Avenue", raw_size_ml=100, market="BE",
        )
        older = OfferObservation(
            listing_key="deloox:1385920",
            observed_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
            price=__import__("decimal").Decimal("39.99"),
            currency="EUR", availability=Availability.IN_STOCK, source="product_page",
            verification=Verification.VERIFIED, product_id=product_100.product_id,
            variant_id=variant_100.variant_id, evidence_url=url, evidence_hash="sha256:older",
        )
        result = repository.record(older_listing, older)
        self.assertFalse(result["published"])
        current = OfferReadRepository(self.connection).search("Liquid Brun", market="BE")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["variant_id"], variant_150.variant_id)
        self.assertEqual(str(current[0]["price"]), "42.89")
        stored_listing = self.connection.execute(
            "SELECT raw_size_ml, raw_title FROM sh_retailer_listings WHERE retailer_id='deloox' AND external_id='1385920'"
        ).fetchone()
        self.assertEqual(stored_listing["raw_size_ml"], 150)
        self.assertIn("150 ml", stored_listing["raw_title"])

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


    def test_listings_without_external_ids_are_keyed_by_url_and_retired_independently(self):
        repository = OfferRepository(self.connection, canonical_catalog=self.catalog)
        product_100 = self.catalog.get("SH-0030")
        variant_100 = next(item for item in product_100.variants if item.variant_id == "VAR-f87146c82d167f4c")
        product_150 = self.catalog.get("SH-0031")
        variant_150 = next(item for item in product_150.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        url_100 = "https://www.deloox.be/produit/100/liquid-brun-100-ml.html"
        url_150 = "https://www.deloox.be/produit/150/liquid-brun-limited-150-ml.html"

        listing_100 = RetailerListing(
            retailer="deloox", external_id=None, product_url=url_100,
            raw_title="French Avenue Liquid Brun 100 ml",
            raw_brand="French Avenue", raw_size_ml=100, market="BE",
        )
        listing_150 = RetailerListing(
            retailer="deloox", external_id=None, product_url=url_150,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="BE",
        )
        result_100 = repository.record(
            listing_100,
            OfferObservation.now(
                listing_key=f"deloox:{url_100}", price=__import__("decimal").Decimal("39.99"),
                currency="EUR", availability=Availability.IN_STOCK, source="product_page",
                verification=Verification.VERIFIED, product_id=product_100.product_id,
                variant_id=variant_100.variant_id, evidence_url=url_100,
                evidence_hash="sha256:no-id-100",
            ),
        )
        result_150 = repository.record(
            listing_150,
            OfferObservation.now(
                listing_key=f"deloox:{url_150}", price=__import__("decimal").Decimal("42.89"),
                currency="EUR", availability=Availability.IN_STOCK, source="product_page",
                verification=Verification.VERIFIED, product_id=product_150.product_id,
                variant_id=variant_150.variant_id, evidence_url=url_150,
                evidence_hash="sha256:no-id-150",
            ),
        )
        self.assertNotEqual(result_100["listing_id"], result_150["listing_id"])
        self.assertEqual(len(OfferReadRepository(self.connection).search("Liquid Brun", market="BE")), 2)

        unresolved = OfferObservation.now(
            listing_key=f"deloox:{url_100}", price=None, currency="EUR",
            availability=Availability.UNKNOWN, source="product_page",
            verification=Verification.UNVERIFIED, evidence_url=url_100,
            evidence_hash="sha256:no-id-100-ambiguous",
        )
        repository.record(listing_100, unresolved, match_status="ambiguous")

        offers = OfferReadRepository(self.connection).search("Liquid Brun", market="BE")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["variant_id"], variant_150.variant_id)
        listing_rows = self.connection.execute(
            "SELECT product_url, canonical_product_id, canonical_variant_id, match_status "
            "FROM sh_retailer_listings WHERE retailer_id='deloox' ORDER BY product_url"
        ).fetchall()
        self.assertEqual(len(listing_rows), 2)
        row_100 = next(row for row in listing_rows if row["product_url"] == url_100)
        row_150 = next(row for row in listing_rows if row["product_url"] == url_150)
        self.assertEqual((row_100["canonical_product_id"], row_100["canonical_variant_id"], row_100["match_status"]), (None, None, "ambiguous"))
        self.assertEqual((row_150["canonical_product_id"], row_150["canonical_variant_id"], row_150["match_status"]), (product_150.product_id, variant_150.variant_id, "matched"))


    def test_stale_unresolved_rematch_does_not_retire_newer_verified_offer(self):
        product = self.catalog.get("SH-0031")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        url = "https://www.deloox.be/produit/1385920/liquid-brun-limited-150-ml.html"
        listing = RetailerListing(
            retailer="deloox", external_id="1385920", product_url=url,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="BE",
        )
        repository = OfferRepository(self.connection, canonical_catalog=self.catalog)
        current = repository.record(
            listing,
            OfferObservation.now(
                listing_key="deloox:1385920", price=__import__("decimal").Decimal("42.89"),
                currency="EUR", availability=Availability.IN_STOCK,
                source="product_page", verification=Verification.VERIFIED,
                product_id=product.product_id, variant_id=variant.variant_id,
                evidence_url=url, evidence_hash="sha256:newer-verified",
            ),
        )
        stale = OfferObservation(
            listing_key="deloox:1385920",
            observed_at=datetime.now(timezone.utc) - timedelta(days=1),
            price=None, currency="EUR", availability=Availability.UNKNOWN,
            source="product_page", verification=Verification.UNVERIFIED,
            evidence_url=url, evidence_hash="sha256:older-ambiguous",
        )
        repository.record(listing, stale, match_status="ambiguous")
        offers = OfferReadRepository(self.connection).search("Liquid Brun", market="BE")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["variant_id"], variant.variant_id)
        row = self.connection.execute(
            "SELECT canonical_product_id, canonical_variant_id, match_status "
            "FROM sh_retailer_listings WHERE retailer_id='deloox' AND external_id='1385920'"
        ).fetchone()
        self.assertEqual(tuple(row), (product.product_id, variant.variant_id, "matched"))



    def test_read_model_never_exposes_price_on_sold_out_offer_if_current_row_is_corrupted(self):
        product = self.catalog.get("SH-0031")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
        url = "https://www.parfumzentrum.de/french-avenue-liquid-brun-limited-150-ml.html"
        listing = RetailerListing(
            retailer="parfumzentrum", external_id="sold-out-price-corruption",
            product_url=url,
            raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
            raw_brand="French Avenue", raw_size_ml=150, market="DE",
        )
        result = OfferRepository(self.connection, canonical_catalog=self.catalog).record(
            listing,
            OfferObservation.now(
                listing_key="parfumzentrum:sold-out-price-corruption",
                price=None, currency="EUR",
                availability=Availability.OUT_OF_STOCK, source="product_page",
                verification=Verification.VERIFIED,
                product_id=product.product_id, variant_id=variant.variant_id,
                evidence_url=url, evidence_hash="sha256:sold-out-price-corruption",
            ),
        )
        self.assertTrue(result["published"])
        # Bypass the defensive table CHECK only to simulate historical/manual
        # corruption; the public read model must still fail closed.
        self.connection.execute("PRAGMA ignore_check_constraints = ON")
        try:
            self.connection.execute(
                "UPDATE sh_offer_observations SET price=39.99 WHERE observation_id=?",
                (result["observation_id"],),
            )
            offers = OfferReadRepository(self.connection).search("Liquid Brun", market="DE")
        finally:
            self.connection.execute("PRAGMA ignore_check_constraints = OFF")
        self.assertFalse(any(row["external_id"] == "sold-out-price-corruption" for row in offers))

    def test_read_model_never_exposes_zero_price_even_if_current_row_is_corrupted(self):
        product = self.catalog.get("SH-0030")
        variant = next(item for item in product.variants if item.variant_id == "VAR-f87146c82d167f4c")
        url = "https://www.parfumzentrum.de/french-avenue-liquid-brun-100-ml.html"
        listing = RetailerListing(
            retailer="parfumzentrum", external_id="zero-price-corruption",
            product_url=url,
            raw_title="French Avenue Liquid Brun Eau de Parfum 100 ml",
            raw_brand="French Avenue", raw_size_ml=100, market="DE",
        )
        result = OfferRepository(self.connection, canonical_catalog=self.catalog).record(
            listing,
            OfferObservation.now(
                listing_key="parfumzentrum:zero-price-corruption",
                price=Decimal("39.99"), currency="EUR",
                availability=Availability.IN_STOCK, source="product_page",
                verification=Verification.VERIFIED,
                product_id=product.product_id, variant_id=variant.variant_id,
                evidence_url=url, evidence_hash="sha256:zero-price-corruption",
            ),
        )
        self.assertTrue(result["published"])
        # Simulate a legacy/manual write bypassing OfferPolicy. The customer
        # read model must still fail closed and never show a free purchasable item.
        self.connection.execute(
            "UPDATE sh_offer_observations SET price=0 WHERE observation_id=?",
            (result["observation_id"],),
        )
        offers = OfferReadRepository(self.connection).search("Liquid Brun", market="DE")
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()

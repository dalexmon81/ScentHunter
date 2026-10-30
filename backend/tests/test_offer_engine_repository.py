from datetime import datetime, timezone
from decimal import Decimal
import unittest

from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.repository import OfferRepository


class Cursor:
    def __init__(self, fail=False):
        self.calls = []
        self.rowcount = 1
        self.fail = fail
        self._fetch = [41, 72]
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail and "INSERT INTO sh_offer_observations" in sql:
            raise RuntimeError("write failed")
    def fetchone(self):
        return (self._fetch.pop(0),)
    def close(self):
        pass


class Connection:
    def __init__(self, fail=False):
        self.cur = Cursor(fail)
        self.commits = 0
        self.rollbacks = 0
    def cursor(self):
        return self.cur
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1


def fixtures(verified=False):
    listing = RetailerListing(
        retailer="deloox", external_id="sku-1",
        product_url="https://www.deloox.be/p/sku-1",
        raw_title="Liquid Brun Limited Edition 150 ml",
        raw_brand="French Avenue", raw_size_ml=150, market="BE",
    )
    observation = OfferObservation.now(
        listing_key="deloox:sku-1", price=Decimal("49.95"),
        currency="EUR", availability=Availability.IN_STOCK,
        source="product_page",
        verification=Verification.VERIFIED if verified else Verification.UNVERIFIED,
        product_id="SH-0031" if verified else None,
        variant_id="VAR-f5aff76b4bb5de8a" if verified else None,
        evidence_url=listing.product_url, evidence_hash="sha256:evidence",
    )
    return listing, observation


class OfferRepositoryTests(unittest.TestCase):
    def test_unverified_observation_is_saved_but_not_published(self):
        conn = Connection()
        listing, observation = fixtures()
        result = OfferRepository(conn).record(listing, observation)
        self.assertFalse(result["published"])
        self.assertEqual(result["policy_reason"], "not_verified")
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertFalse(any("INSERT INTO sh_current_offers" in sql for sql, _ in conn.cur.calls))

    def test_verified_fresh_offer_is_published_atomically(self):
        conn = Connection()
        listing, observation = fixtures(verified=True)
        result = OfferRepository(conn).record(listing, observation)
        self.assertTrue(result["published"])
        self.assertEqual(result["listing_id"], 41)
        self.assertEqual(result["observation_id"], 72)
        self.assertEqual(conn.commits, 1)
        self.assertTrue(any("INSERT INTO sh_current_offers" in sql for sql, _ in conn.cur.calls))

    def test_any_write_failure_rolls_back_the_unit_of_work(self):
        conn = Connection(fail=True)
        listing, observation = fixtures()
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            OfferRepository(conn).record(listing, observation)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()

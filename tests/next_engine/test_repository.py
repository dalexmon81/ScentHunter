import tempfile
import unittest
from pathlib import Path
from scenthunter_next_engine.models import Product, Variant, Offer, SourceObservation
from scenthunter_next_engine.repository import SQLiteOfferRepository


def observation(price=12999, observed_at="2026-01-01T00:00:00+00:00"):
    p = Product("p1", "Maison Example", "Example Eau de Parfum", "1234567890123")
    v = Variant("v1", "p1", "edp", 100, 1)
    o = Offer("o1", "v1", "shop_a", "https://shop.example/product/1", price, "EUR",
              "in_stock", observed_at)
    return SourceObservation("shop_a", o.product_url, observed_at, p, v, o,
                             "Maison Example EDP 100ml", str(price / 100), "fixture-v1", "trace-1")


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = SQLiteOfferRepository(Path(self.tmp.name) / "next.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_replay_is_idempotent(self):
        obs = observation()
        self.assertTrue(self.repo.save_observation(obs))
        self.assertFalse(self.repo.save_observation(obs))
        self.assertEqual(self.repo.counts()["offers"], 1)
        self.assertEqual(self.repo.counts()["observations"], 1)

    def test_valid_update_changes_price(self):
        self.repo.save_observation(observation(12999))
        self.repo.save_observation(observation(11999, "2026-01-02T00:00:00+00:00"))
        rows = self.repo.current_offers(store="shop_a")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_minor"], 11999)
        self.assertEqual(self.repo.counts()["observations"], 2)

    def test_failure_does_not_erase_valid_offer(self):
        self.repo.save_observation(observation())
        self.repo.record_failure(store="shop_a", source_url="https://shop.example/product/1",
                                 kind="transient_network", message="timeout", retryable=True,
                                 occurred_at="2026-01-02T00:00:00+00:00")
        self.assertEqual(self.repo.current_offers()[0]["price_minor"], 12999)


if __name__ == "__main__":
    unittest.main()

"""Public comparison must contain only offers with confirmed stock."""
import unittest

from main import _aggregate_identity_results


def make_offer(**overrides):
    row = {
        "_match_status": "matched",
        "catalog_id": "SH-0030",
        "canonical_brand": "French Avenue",
        "brand": "French Avenue",
        "canonical_name": "Liquid Brun",
        "name": "Liquid Brun Eau de Parfum 100 ml",
        "store": "parfumcity",
        "price_num": 32.99,
        "price": "32.99",
        "size_ml": 100,
        "url": "https://www.parfumcity.nl/products/liquid-brun-french-avenue-100ml",
        "available": True,
        "availability": "in_stock",
    }
    row.update(overrides)
    return row


class PublicOfferStockGuardTests(unittest.TestCase):
    def test_confirmed_in_stock_offer_is_published(self):
        groups, unresolved = _aggregate_identity_results([make_offer()])
        self.assertEqual(unresolved, [])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["offers"]), 1)

    def test_sold_out_offer_is_not_published_even_with_price(self):
        groups, unresolved = _aggregate_identity_results([
            make_offer(available=False, availability="out_of_stock")
        ])
        self.assertEqual(groups, [])
        self.assertEqual(unresolved, [])

    def test_unknown_stock_is_not_published(self):
        groups, unresolved = _aggregate_identity_results([
            make_offer(available=None, availability="unknown")
        ])
        self.assertEqual(groups, [])
        self.assertEqual(unresolved, [])

    def test_string_available_signal_is_accepted(self):
        groups, unresolved = _aggregate_identity_results([
            make_offer(available=None, availability="available")
        ])
        self.assertEqual(unresolved, [])
        self.assertEqual(len(groups), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from bs4 import BeautifulSoup

from backend.scrapers.deloox.scraper import page_offer_price


class DelooxPriceEvidenceTests(unittest.TestCase):
    def test_visible_current_price_wins_over_stale_jsonld(self):
        soup = BeautifulSoup('<span class="price-current">42,89 €</span>', "lxml")
        self.assertEqual(page_offer_price({"price": "49.99"}, soup), 42.89)

    def test_conflicting_visible_prices_fail_closed(self):
        soup = BeautifulSoup(
            '<span class="price">42,89 €</span><span class="price">49,99 €</span>',
            "lxml",
        )
        self.assertIsNone(page_offer_price({"price": "49.99"}, soup))

    def test_structured_price_is_used_only_without_scoped_price_markup(self):
        soup = BeautifulSoup('<h1>Limited Edition 150 ml</h1><p>Shipping from 50 €</p>', "lxml")
        self.assertEqual(page_offer_price({"price": "42.89"}, soup), 42.89)


if __name__ == "__main__":
    unittest.main()

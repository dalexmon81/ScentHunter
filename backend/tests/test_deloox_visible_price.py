from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from backend.scrapers.deloox.scraper import visible_price


class DelooxVisiblePriceTests(unittest.TestCase):
    def test_prefers_explicit_current_price_over_crossed_out_price(self):
        soup = BeautifulSoup(
            """
            <div class="product-price">
              <span class="price-old">59,99 €</span>
              <span class="price-current">42,89 €</span>
            </div>
            """,
            "lxml",
        )
        self.assertEqual(visible_price(soup), 42.89)

    def test_rejects_ambiguous_scoped_prices_without_current_marker(self):
        soup = BeautifulSoup(
            """
            <span class="price">42,89 €</span>
            <span class="price">49,99 €</span>
            """,
            "lxml",
        )
        self.assertIsNone(visible_price(soup))

    def test_ignores_unrelated_numbers_outside_price_markup(self):
        soup = BeautifulSoup(
            """
            <nav>Speciale offerte da 19,99 €</nav>
            <h1>Liquid Brun Limited Edition 150 ml</h1>
            <p>Consegna gratuita da 50 €</p>
            """,
            "lxml",
        )
        self.assertIsNone(visible_price(soup))


if __name__ == "__main__":
    unittest.main()

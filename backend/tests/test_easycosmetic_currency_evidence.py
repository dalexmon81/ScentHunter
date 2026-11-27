from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.connectors.legacy_scrapers import LegacyScraperConnector
from scrapers.easycosmetic import scraper


PRODUCT_URL = (
    "https://www.easycosmetic.de/giorgio-armani/acqua-di-gio/"
    "giorgio-armani-acqua-di-gio-eau-de-parfum-100ml.aspx"
)


class EasycosmeticCurrencyEvidenceTests(unittest.TestCase):
    def test_visible_euro_price_is_bound_to_the_selected_product_price(self):
        html = """
        <html><body><main><article class="product-detail">
          <h1>Giorgio Armani Acqua di Gio Eau de Parfum 100 ml</h1>
          <div class="product-price"><span>89,99</span><span> €</span></div>
          <p>Auf Lager</p>
        </article></main></body></html>
        """
        parsed = scraper._parse_product_html(PRODUCT_URL, html)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_num"], 89.99)
        self.assertTrue(parsed["available"])
        evidence = parsed["raw_data"]["currency_evidence"]
        self.assertEqual(evidence["currency"], "EUR")
        self.assertEqual(evidence["source"], "product_price_display")
        self.assertEqual(evidence["matched_price"], "89.99")

        connector = LegacyScraperConnector("easycosmetic", SimpleNamespace())
        normalized = connector.parse_raw(parsed)
        self.assertEqual(normalized["price"], "89.99")
        self.assertEqual(normalized["currency"], "EUR")
        self.assertTrue(normalized["currency_explicit"])

    def test_numeric_price_without_visible_currency_is_not_explicit_eur(self):
        html = """
        <html><body><main><article class="product-detail">
          <h1>Giorgio Armani Acqua di Gio Eau de Parfum 100 ml</h1>
          <div class="product-price" data-price="89.99">89,99</div>
          <p>Auf Lager</p>
        </article></main></body></html>
        """
        parsed = scraper._parse_product_html(PRODUCT_URL, html)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_num"], 89.99)
        self.assertNotIn("currency_evidence", parsed["raw_data"])

        connector = LegacyScraperConnector("easycosmetic", SimpleNamespace())
        normalized = connector.parse_raw(parsed)
        self.assertFalse(normalized["currency_explicit"])

    def test_euro_evidence_for_a_different_visible_amount_is_rejected(self):
        html = """
        <html><body><main><article class="product-detail">
          <h1>Giorgio Armani Acqua di Gio Eau de Parfum 100 ml</h1>
          <div class="product-price" data-price="89.99">79,99 €</div>
          <p>Auf Lager</p>
        </article></main></body></html>
        """
        parsed = scraper._parse_product_html(PRODUCT_URL, html)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_num"], 89.99)
        self.assertNotIn("currency_evidence", parsed["raw_data"])


if __name__ == "__main__":
    unittest.main()

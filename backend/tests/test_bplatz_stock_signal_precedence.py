import importlib.util
from pathlib import Path
import unittest


SCRAPER_PATH = Path(__file__).resolve().parents[1] / "scrapers" / "bplatz" / "scraper.py"
SPEC = importlib.util.spec_from_file_location("bplatz_scraper_stock_test", SCRAPER_PATH)
SCRAPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRAPER)


class BplatzStockSignalPrecedenceTests(unittest.TestCase):
    def test_unavailable_is_not_misread_as_available(self):
        self.assertEqual(SCRAPER.availability_from_text("Product unavailable"), "out_of_stock")

    def test_out_of_stock_wins_over_positive_words_elsewhere(self):
        self.assertEqual(
            SCRAPER.availability_from_text("Available soon — currently out of stock"),
            "out_of_stock",
        )

    def test_explicit_in_stock_remains_available(self):
        self.assertEqual(SCRAPER.availability_from_text("Add to cart - In stock"), "in_stock")

    def test_no_stock_evidence_remains_unknown(self):
        self.assertEqual(SCRAPER.availability_from_text("See product details"), "unknown")

    def test_price_currency_and_stock_are_bound_to_the_same_offer(self):
        html = """
        <html><body><h1>Liquid Brun Eau de Parfum 100 ml</h1>
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Liquid Brun Eau de Parfum 100 ml",
          "offers": [
            {"price": "25.99", "priceCurrency": "EUR",
             "availability": "https://schema.org/InStock"},
            {"price": "31.99", "priceCurrency": "USD",
             "availability": "https://schema.org/OutOfStock"}
          ]
        }
        </script></body></html>
        """
        parsed = SCRAPER.parse_product_html(
            html, "https://bplatz.de/products/liquid-brun", "Liquid Brun"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_num"], 25.99)
        self.assertEqual(parsed["currency"], "EUR")
        self.assertTrue(parsed["currency_explicit"])
        self.assertEqual(parsed["availability"], "in_stock")

    def test_currency_and_stock_are_not_borrowed_from_another_offer(self):
        html = """
        <html><body><h1>Liquid Brun Eau de Parfum 100 ml</h1>
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Liquid Brun Eau de Parfum 100 ml",
          "offers": [
            {"price": "25.99"},
            {"price": "31.99", "priceCurrency": "EUR",
             "availability": "https://schema.org/InStock"}
          ]
        }
        </script></body></html>
        """
        parsed = SCRAPER.parse_product_html(
            html, "https://bplatz.de/products/liquid-brun", "Liquid Brun"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_num"], 25.99)
        self.assertEqual(parsed["currency"], "EUR")
        self.assertFalse(parsed["currency_explicit"])
        self.assertEqual(parsed["availability"], "unknown")


if __name__ == "__main__":
    unittest.main()

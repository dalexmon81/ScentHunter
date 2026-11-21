import importlib.util
from pathlib import Path
import unittest

from scrapers.bplatz.scraper import parse_product_html


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

    def test_fallback_price_patterns_parse_visible_euro_price(self):
        html = """
        <html><head>
          <script type="application/ld+json">
          {"@type":"Product","name":"Test Perfume Eau de Parfum 100 ml",
           "brand":{"@type":"Brand","name":"Test Brand"},
           "offers":{"priceCurrency":"EUR","availability":"https://schema.org/InStock"}}
          </script>
        </head><body>
          <h1>Test Perfume Eau de Parfum 100 ml</h1>
          <div>Retail price € 27.50</div>
          <div>In stock</div>
        </body></html>
        """
        parsed = parse_product_html(
            html, "https://en.bplatz.de/products/test-perfume", "Test Perfume"
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["price_num"], 27.5)
        self.assertTrue(parsed["currency_explicit"])
        self.assertEqual(parsed["availability"], "in_stock")


if __name__ == "__main__":
    unittest.main()

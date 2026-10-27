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


if __name__ == "__main__":
    unittest.main()

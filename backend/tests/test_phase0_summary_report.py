import tempfile
import unittest
from pathlib import Path

from scenthunter_next_engine.baseline_summary import SUMMARY_COLUMNS, summarize_rows
from scenthunter_next_engine.baseline_report import SUPPORTED_STORES


class Phase0SummaryReportTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "store": store,
                "price": "12.50",
                "currency": "EUR",
                "offer_url": f"https://{store}.example/item",
                "availability": "in_stock",
                "match_status": "matched" if index == 0 else "unresolved",
            }
            for index, store in enumerate(SUPPORTED_STORES)
        ]

    def test_emits_per_store_and_total_metrics(self):
        rows = summarize_rows(self._rows(), catalog_product_count=123)
        self.assertEqual(len(rows), len(SUPPORTED_STORES) + 1)
        self.assertEqual(tuple(rows[0].keys()), SUMMARY_COLUMNS)
        self.assertEqual(rows[0]["catalog_product_count"], 123)
        self.assertEqual(rows[0]["valid_price_pct"], 100.0)
        self.assertEqual(rows[0]["valid_url_pct"], 100.0)
        self.assertEqual(rows[0]["valid_stock_pct"], 100.0)
        self.assertEqual(rows[0]["matched_match_count"], 1)
        self.assertEqual(rows[-1]["store"], "TOTAL")
        self.assertEqual(rows[-1]["total_offers"], 9)
        self.assertEqual(rows[-1]["matched_match_count"], 1)
        self.assertEqual(rows[-1]["unresolved_match_count"], 8)

    def test_reports_invalid_price_url_and_stock_as_zero_percent(self):
        rows = self._rows()
        rows[0].update(price="0", offer_url="not-a-url", availability="unknown")
        result = summarize_rows(rows, catalog_product_count=10)[0]
        self.assertEqual(result["valid_price_pct"], 0.0)
        self.assertEqual(result["valid_url_pct"], 0.0)
        self.assertEqual(result["valid_stock_pct"], 0.0)

    def test_rejects_missing_active_store_instead_of_fabricating_zero_rows(self):
        with self.assertRaisesRegex(ValueError, "No offers for required active retailer"):
            summarize_rows(self._rows()[:-1], catalog_product_count=10)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.validate_phase0_baseline import STORES, validate_baseline


class Phase0BaselineValidationTests(unittest.TestCase):
    def write_csv(self, rows, headers=None):
        temp = tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                           suffix=".csv", delete=False)
        self.addCleanup(lambda: Path(temp.name).unlink(missing_ok=True))
        fields = headers or [
            "store", "canonical_product_id", "brand", "fragrance", "concentration",
            "size_ml", "gtin", "external_product_id", "offer_url", "price",
            "currency", "availability", "captured_at", "source", "match_status",
            "match_confidence", "is_valid_offer",
        ]
        writer = csv.DictWriter(temp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        temp.close()
        return temp.name

    def valid_row(self, store):
        return {
            "store": store, "canonical_product_id": f"canonical-{store}",
            "brand": "Brand", "fragrance": "Fragrance",
            "concentration": "EDP", "size_ml": "100", "gtin": "",
            "external_product_id": f"sku-{store}",
            "offer_url": f"https://{store}.example/product",
            "price": "49.90", "currency": "EUR", "availability": "in_stock",
            "captured_at": "2026-11-06T10:00:00Z", "source": "authorized_feed",
            "match_status": "matched", "match_confidence": "0.99",
            "is_valid_offer": "true",
        }

    def test_accepts_one_valid_distinct_offer_per_active_store(self):
        result = validate_baseline(self.write_csv([self.valid_row(s) for s in STORES]))
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["offer_count"], 9)

    def test_status_rows_do_not_count_as_offers_and_notino_is_required(self):
        rows = [self.valid_row(s) for s in STORES if s != "notino"]
        rows.append({"store": "notino", "source": "", "offer_url": ""})
        result = validate_baseline(self.write_csv(rows))
        self.assertFalse(result["passed"])
        self.assertIn("notino", result["store_offer_counts"])
        self.assertTrue(any("notino" in error for error in result["errors"]))

    def test_rejects_http_invalid_price_and_duplicate_offer(self):
        row = self.valid_row("notino")
        row["offer_url"] = "http://notino.example/product"
        row["price"] = "0"
        result = validate_baseline(self.write_csv([row, row.copy()] + [
            self.valid_row(s) for s in STORES if s != "notino"
        ]))
        self.assertFalse(result["passed"])
        self.assertTrue(any("https" in error for error in result["errors"]))
        self.assertTrue(any("positive" in error for error in result["errors"]))
        self.assertTrue(any("duplicate_offer_key" in error for error in result["errors"]))

    def test_rejects_unexpected_store(self):
        rows = [self.valid_row(s) for s in STORES]
        rows.append(self.valid_row("amazon_de"))
        result = validate_baseline(self.write_csv(rows))
        self.assertFalse(result["passed"])
        self.assertTrue(any("unexpected_store" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()

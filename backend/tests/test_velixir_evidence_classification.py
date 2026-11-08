"""Regression guard for collection-level evidence classification.

A collection listing is not an individual product-detail page. Keep this
specific source/status invariant so future catalog harvests cannot silently
upgrade the whole Velixir range to individually verified evidence.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class VelixirEvidenceClassificationTests(unittest.TestCase):
    def test_general_collection_url_is_not_individual_detail_evidence(self):
        rows = [
            row for row in CATALOG.get("products", [])
            if (row.get("brand_name") or row.get("brand") or "").strip() == "Velixir"
            and row.get("source_url") == "https://velixirparfums.com/collections/all"
        ]
        self.assertTrue(rows, "Expected the known Velixir collection-backed catalog rows.")
        incorrectly_verified = [
            row.get("canonical_name") or row.get("name")
            for row in rows
            if row.get("identity_status") != "source_listed_name"
        ]
        self.assertEqual(
            incorrectly_verified,
            [],
            "A general collection URL supports listed-name evidence, not individual detail verification.",
        )

    def test_no_velixir_product_is_missing_provenance(self):
        rows = [
            row for row in CATALOG.get("products", [])
            if (row.get("brand_name") or row.get("brand") or "").strip() == "Velixir"
        ]
        missing = [
            row.get("canonical_name") or row.get("name")
            for row in rows
            if not str(row.get("source_url") or "").strip()
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()

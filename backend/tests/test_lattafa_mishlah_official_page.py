"""Official detail-page evidence for Lattafa Mishlah."""

import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
PRODUCT_URL = "https://lattafa.com/product/lattafa-mishlah/"


class LattafaMishlahOfficialPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_existing_canonical_identity_has_official_detail_evidence(self):
        matches = [
            p for p in self.products
            if p.get("brand_name") == "Lattafa"
            and p.get("canonical_name") == "Mishlah"
        ]
        self.assertEqual(len(matches), 1)
        product = matches[0]
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("source_url"), PRODUCT_URL)
        self.assertEqual(product.get("source_evidence_url"), PRODUCT_URL)

    def test_one_explicit_100ml_variant_without_inferred_concentration(self):
        product = next(
            p for p in self.products
            if p.get("brand_name") == "Lattafa"
            and p.get("canonical_name") == "Mishlah"
        )
        matches = [
            v for v in self.variants
            if v.get("product_id") == product["product_id"]
            and v.get("size_ml") == 100
        ]
        self.assertEqual(len(matches), 1)
        self.assertNotIn("concentration", matches[0])
        for forbidden in ("price", "stock", "shipping_cost", "store_url"):
            self.assertNotIn(forbidden, matches[0])

    def test_catalog_keeps_one_canonical_identity_and_unique_variant_ids(self):
        products = [
            p for p in self.products
            if p.get("brand_name") == "Lattafa"
            and p.get("canonical_name") == "Mishlah"
        ]
        self.assertEqual(len(products), 1)
        ids = [v.get("variant_id") for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the merged Khadlaj catalog and SKU evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

class KhadlajCatalogReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"]
        cls.product_ids = {p["product_id"] for p in cls.products}
        cls.variants = [v for v in CATALOG["variants"] if v.get("product_id") in cls.product_ids]
        cls.by_name = {p.get("canonical_name") or p.get("name"): p for p in cls.products}

    def test_166_khadlaj_canonical_identities_are_present(self):
        self.assertEqual(len(self.products), 166)
        self.assertEqual(len(self.by_name), 166)

    def test_156_variants_have_unique_ids_and_parent_sizes(self):
        self.assertEqual(len(self.variants), 156)
        ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))
        for variant in self.variants:
            product = next(p for p in self.products if p["product_id"] == variant["product_id"])
            with self.subTest(product=product["canonical_name"], size=variant["size_ml"]):
                self.assertIn(variant["size_ml"], product.get("formats_ml", []))

    def test_every_variant_has_auditable_source_evidence(self):
        for variant in self.variants:
            with self.subTest(variant=variant["variant_id"]):
                self.assertTrue(variant.get("source_evidence_url"))

    def test_shiyaaka_rose_gold_remains_name_only_until_a_product_page_is_found(self):
        product = self.by_name["Shiyaaka Rose Gold"]
        self.assertEqual(product["identity_status"], "source_listed_name")
        self.assertNotIn("formats_ml", product)
        self.assertNotIn("concentration", product)
        self.assertFalse(any(v["product_id"] == product["product_id"] for v in self.variants))

    def test_hareem_al_sultan_oil_and_spray_are_distinct_products(self):
        oil = self.by_name["Hareem Al Sultan Gold"]
        spray = self.by_name["Hareem Al Sultan"]
        self.assertEqual(oil.get("concentration"), "Perfume Oil")
        self.assertEqual(spray.get("concentration"), "Eau de Parfum")
        oil_variants = [v for v in self.variants if v["product_id"] == oil["product_id"]]
        spray_variants = [v for v in self.variants if v["product_id"] == spray["product_id"]]
        self.assertTrue(any(v["size_ml"] == 35 for v in oil_variants))
        self.assertTrue(any(v["size_ml"] == 75 for v in spray_variants))

    def test_maya_is_a_perfume_oil_not_a_spray_variant(self):
        product = self.by_name["Maya"]
        self.assertEqual(product.get("concentration"), "Perfume Oil")
        variant = next(v for v in self.variants if v["product_id"] == product["product_id"])
        self.assertEqual(variant.get("concentration"), "Perfume Oil")
        self.assertEqual(variant.get("size_ml"), 20)

if __name__ == "__main__":
    unittest.main()

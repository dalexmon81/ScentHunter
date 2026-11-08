"""Regression tests for Bujairami's merged A-L and official variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

class BujairamiCatalogReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in CATALOG["products"] if p.get("brand") == "Bujairami"]
        cls.product_ids = {p["product_id"] for p in cls.products}
        cls.variants = [v for v in CATALOG["variants"] if v.get("product_id") in cls.product_ids]
        cls.by_name = {p.get("canonical_name") or p.get("name"): p for p in cls.products}

    def test_671_bujairami_canonical_identities_are_present(self):
        self.assertEqual(len(self.products), 671)
        self.assertEqual(len(self.by_name), 671)

    def test_eight_variants_are_unique_sourced_and_match_parent_sizes(self):
        self.assertEqual(len(self.variants), 8)
        ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(ids), len(set(ids)))
        pairs = [(v["product_id"], v["size_ml"]) for v in self.variants]
        self.assertEqual(len(pairs), len(set(pairs)))
        for variant in self.variants:
            product = next(p for p in self.products if p["product_id"] == variant["product_id"])
            with self.subTest(product=product["canonical_name"], size=variant["size_ml"]):
                self.assertTrue(variant.get("source_evidence_url"))
                self.assertIn(variant["size_ml"], product.get("formats_ml", []))
                self.assertNotIn("concentration", variant)

    def test_only_two_range_names_lack_product_specific_evidence(self):
        missing = {p["canonical_name"] for p in self.products if not p.get("source_evidence_url")}
        self.assertEqual(missing, {"Gold Coast Shiraz", "Sunrise in Sydney"})

    def test_gday_has_official_100ml_size_without_inferred_concentration(self):
        product = self.by_name["G’Day"]
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product.get("formats_ml"), [100])
        self.assertNotIn("concentration", product)
        variant = next(v for v in self.variants if v["product_id"] == product["product_id"])
        self.assertEqual(variant["size_ml"], 100)
        self.assertEqual(variant["source_evidence_url"], product["source_evidence_url"])

    def test_the_fuck_up_has_a_direct_official_50ml_product_page(self):
        product = self.by_name["The F*ck Up"]
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product.get("formats_ml"), [50])
        self.assertEqual(product["source_url"], "https://bujairami.com.au/products/the-f-ck-up-original-creation")
        variant = next(v for v in self.variants if v["product_id"] == product["product_id"])
        self.assertEqual(variant["size_ml"], 50)
        self.assertEqual(variant["source_evidence_url"], product["source_url"])

    def test_midnight_in_melbourne_name_is_verified_but_no_size_is_inferred(self):
        product = self.by_name["Midnight in Melbourne"]
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertTrue(product["source_url"].endswith("/midnight-in-melbourne-bujairami-original-niche"))
        self.assertNotIn("formats_ml", product)
        self.assertFalse(any(v["product_id"] == product["product_id"] for v in self.variants))

    def test_love_spell_has_both_confirmed_sizes(self):
        product = self.by_name["Love Spell"]
        sizes = {v["size_ml"] for v in self.variants if v["product_id"] == product["product_id"]}
        self.assertEqual(sizes, {50, 100})

if __name__ == "__main__":
    unittest.main()

"""Regression tests for Paris Corner Pendora registry spelling and official page."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class ParisCornerPendoraRegistryFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Paris Corner"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "paris_corner_catalog"
        )

    def test_attratus_is_an_alias_of_official_attractus_identity(self):
        product = self.products["Attractus"]
        self.assertIn("Attratus", product["aliases"])
        self.assertIn("Paris Corner Attratus", product["aliases"])
        rows = [
            p for p in self.family["products"]
            if p["canonical_name"] == "Attractus"
        ]
        self.assertEqual(len(rows), 1)
        self.assertIn("Attratus", rows[0]["aliases"])
        self.assertFalse(any(p["canonical_name"] == "Attratus" for p in self.family["products"]))

    def test_harrier_absoulte_has_official_pendora_product_and_variant(self):
        product = self.products["Harrier Absoulte"]
        url = "https://www.pariscornerperfumes.com/products/harrier-absoulte"
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], url)
        self.assertEqual(product["source_evidence_url"], url)
        self.assertEqual(product["collection_name"], "Pendora Scents")
        self.assertEqual(product["formats_ml"], [100])
        self.assertEqual(product["concentration"], "Eau de Parfum")
        matches = [
            v for v in self.variants
            if v["product_id"] == product["product_id"]
            and v.get("size_ml") == 100
            and v.get("concentration") == "Eau de Parfum"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source_url"], url)

    def test_catalog_identity_and_variant_ids_remain_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()

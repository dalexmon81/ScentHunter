"""Regression coverage for Paris Corner spelling reconciliation and Harrier variant evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class ParisCornerSpellingReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Paris Corner"
        }
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "paris_corner_catalog"
        )

    def test_attratus_resolves_to_existing_attractus_identity(self):
        product = self.products["Attractus"]
        self.assertIn("Attratus", product["aliases"])
        registry_rows = [
            p for p in self.family["products"]
            if p["canonical_name"] == "Attractus"
        ]
        self.assertEqual(len(registry_rows), 1)
        self.assertIn("Attratus", registry_rows[0]["aliases"])
        self.assertFalse(any(
            p["canonical_name"] == "Attratus"
            for p in self.family["products"]
        ))

    def test_harrier_absoulte_is_alias_of_harrier_absolute(self):
        product = self.products["Harrier Absolute"]
        self.assertIn("Harrier Absoulte", product["aliases"])
        self.assertEqual(
            product["source_evidence_url"],
            "https://www.pariscornerperfumes.com/products/harrier-absoulte",
        )
        self.assertEqual(product["formats_ml"], [100])
        self.assertEqual(product["concentration"], "Eau de Parfum")
        matches = [
            v for v in CATALOG["variants"]
            if v.get("product_id") == product["product_id"]
            and v.get("size_ml") == 100
            and v.get("concentration") == "Eau de Parfum"
        ]
        self.assertEqual(len(matches), 1)

    def test_registry_has_no_duplicate_canonical_names_after_reconciliation(self):
        names = [p["canonical_name"].casefold() for p in self.family["products"]]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()

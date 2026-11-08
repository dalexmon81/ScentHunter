"""Regression coverage for the official Harrier Absoulte spelling and canonical mapping."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
URL = "https://www.pariscornerperfumes.com/products/harrier-absoulte"


class ParisCornerHarrierAbsoulteAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.product = next(
            p for p in CATALOG["products"]
            if p.get("brand_name") == "Paris Corner"
            and p.get("canonical_name") == "Harrier Absolute"
        )
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "paris_corner_catalog"
        )

    def test_official_spelling_is_an_alias_of_existing_canonical_identity(self):
        self.assertIn("Harrier Absoulte", self.product["aliases"])
        self.assertIn("Paris Corner Harrier Absoulte", self.product["aliases"])
        self.assertEqual(self.product["source_url"], URL)
        self.assertEqual(self.product["source_evidence_url"], URL)
        self.assertEqual(self.product["identity_status"], "source_verified_name")
        self.assertEqual(self.product["formats_ml"], [100])
        self.assertEqual(self.product["concentration"], "Eau de Parfum")

    def test_one_100ml_edp_variant_is_linked_to_existing_product(self):
        matches = [
            v for v in CATALOG["variants"]
            if v.get("product_id") == self.product["product_id"]
            and v.get("size_ml") == 100
            and v.get("concentration") == "Eau de Parfum"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source_url"], URL)
        self.assertIn("Harrier Absoulte 100 ml", matches[0]["aliases"])

    def test_family_registry_has_one_canonical_row_and_no_duplicate_typo_row(self):
        rows = [
            p for p in self.family["products"]
            if p["canonical_name"] in {"Harrier Absolute", "Harrier Absoulte"}
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonical_name"], "Harrier Absolute")
        self.assertIn("Harrier Absoulte", rows[0]["aliases"])
        names = [p["canonical_name"].casefold() for p in self.family["products"]]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()

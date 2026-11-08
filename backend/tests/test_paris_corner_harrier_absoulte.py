"""Regression coverage for the official Paris Corner Harrier Absoulte product page."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class ParisCornerHarrierAbsoulteTests(unittest.TestCase):
    def test_official_spelling_maps_to_existing_canonical_identity(self):
        product = next(
            p for p in CATALOG["products"]
            if p.get("brand_name") == "Paris Corner"
            and p.get("canonical_name") == "Harrier Absolute"
        )
        url = "https://www.pariscornerperfumes.com/products/harrier-absoulte"
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], url)
        self.assertEqual(product["source_evidence_url"], url)
        self.assertIn("Harrier Absoulte", product["aliases"])
        self.assertEqual(product["formats_ml"], [100])
        self.assertEqual(product["concentration"], "Eau de Parfum")
        matches = [
            v for v in CATALOG["variants"]
            if v.get("product_id") == product["product_id"]
            and v.get("size_ml") == 100
            and v.get("concentration") == "Eau de Parfum"
        ]
        self.assertEqual(len(matches), 1)

    def test_family_registry_uses_canonical_spelling_and_alias(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "paris_corner_catalog"
        )
        registry_product = next(
            p for p in family["products"]
            if p["canonical_name"] == "Harrier Absolute"
        )
        self.assertIn("Harrier Absoulte", registry_product["aliases"])
        self.assertIn(100, registry_product.get("formats_ml", []))
        self.assertFalse(any(
            p["canonical_name"] == "Harrier Absoulte"
            for p in family["products"]
        ))


if __name__ == "__main__":
    unittest.main()

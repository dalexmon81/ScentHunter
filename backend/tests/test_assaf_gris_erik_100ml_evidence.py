"""Variant-level EDP evidence for the official Assaf Gris Erik 100 ml page."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class AssafGrisErik100mlEvidenceTests(unittest.TestCase):
    def test_only_100ml_variant_is_verified_as_edp(self):
        product = next(
            p for p in CATALOG["products"]
            if p.get("brand_name") == "Assaf" and p.get("canonical_name") == "Gris Erik"
        )
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        hundred = next(v for v in variants if v.get("size_ml") == 100)
        two_hundred = next(v for v in variants if v.get("size_ml") == 200)
        official_url = "https://assaf.ae/products/edp-gris-erik-100ml"
        self.assertEqual(hundred.get("variant_id"), "SHV-SH-ASSAF-HARVEST-061-100-000")
        self.assertEqual(hundred.get("concentration"), "Eau de Parfum")
        self.assertEqual(hundred.get("source_url"), official_url)
        self.assertEqual(hundred.get("source_evidence_url"), official_url)
        self.assertIsNone(two_hundred.get("concentration"))
        self.assertIsNone(two_hundred.get("source_url"))
        self.assertNotIn("concentration", product)


if __name__ == "__main__":
    unittest.main()

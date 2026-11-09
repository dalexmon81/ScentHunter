"""Tests for individually verified Khadlaj Muse and Icon product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class KhadlajNewLaunchTests(unittest.TestCase):
    def test_existing_listing_identities_are_upgraded_with_official_detail_evidence(self):
        expected = {
            "Muse": ("https://khadlaj-perfumes.com/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women", "Eau de Parfum", "6298043072748"),
            "Icon": ("https://khadlaj-perfumes.com/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men", "Eau de Parfum", "6298043071215"),
        }
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"}
        for name, (url, concentration, gtin) in expected.items():
            with self.subTest(product=name):
                product = products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["concentration"], concentration)
                self.assertEqual(product["formats_ml"], [100])
                variants = [v for v in CATALOG["variants"] if v["product_id"] == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], concentration)
                self.assertEqual(variants[0]["gtin"], gtin)
                self.assertEqual(variants[0]["source_evidence_url"], url)

    def test_new_launches_are_in_khadlaj_family_registry(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue({"Muse", "Icon"}.issubset(names))


if __name__ == "__main__":
    unittest.main()

"""Regression tests for Al Haramain verified product-detail additions."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class AlHaramainDetailAdditionsTests(unittest.TestCase):
    def test_new_product_pages_and_variants_are_explicitly_verified(self):
        expected = {
            "Harmony": ("https://shop.alharamainperfumes.com/eu/haramain-harmony-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "Freya": ("https://shop.alharamainperfumes.com/eu/haramain-freya-100ml-eau-de-parfum.html", "Eau de Parfum"),
            "L'Aventure Extreme": ("https://shop.alharamainperfumes.com/eu/haramain-l-aventure-extreme-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
            "Amber Oud Gold Lux": ("https://shop.alharamainperfumes.com/default/haramain-amber-oud-gold-lux-100ml-extrait-de-parfum.html", "Extrait de Parfum"),
        }
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Al Haramain"}
        for name, (url, concentration) in expected.items():
            with self.subTest(product=name):
                p = products[name]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["concentration"], concentration)
                variants = [v for v in CATALOG["variants"] if v["product_id"] == p["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], concentration)
                self.assertEqual(variants[0]["source_evidence_url"], url)

    def test_family_registry_contains_new_verified_names(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "al_haramain_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue({"Harmony", "Freya", "L'Aventure Extreme", "Amber Oud Gold Lux"}.issubset(names))


if __name__ == "__main__":
    unittest.main()

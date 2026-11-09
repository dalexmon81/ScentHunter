"""Regression tests for five newly verified Al Haramain launches."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class AlHaramainNewLaunchTests(unittest.TestCase):
    def test_five_new_launches_have_official_product_page_evidence(self):
        expected = {
            "Haramain Camellia": ("https://shop.alharamainperfumes.com/eu/haramain-camellia.html", "Extrait de Parfum", None),
            "Amber Oud Smell Dubai": ("https://shop.alharamainperfumes.com/eu/haramain-amber-oud-smell-dubai-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Sameera": ("https://shop.alharamainperfumes.com/eu/haramain-sameera-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Empire Aromatique Ombre": ("https://shop.alharamainperfumes.com/eu/haramain-empire-aromatique-ombre-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Leif": ("https://shop.alharamainperfumes.com/eu/haramain-leif-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        }
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand_name") == "Al Haramain"
        }
        variants = CATALOG["variants"]
        for name, (url, concentration, size) in expected.items():
            with self.subTest(product=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["concentration"], concentration)
                matching = [v for v in variants if v["product_id"] == product["product_id"]]
                if size is None:
                    self.assertEqual(matching, [])
                    self.assertNotIn("formats_ml", product)
                else:
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0]["size_ml"], size)
                    self.assertEqual(matching[0]["concentration"], concentration)
                    self.assertEqual(matching[0]["source_evidence_url"], url)

    def test_new_launches_are_registered_in_al_haramain_family(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "al_haramain_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        for name in ("Haramain Camellia", "Amber Oud Smell Dubai", "Sameera", "Empire Aromatique Ombre", "Leif"):
            self.assertIn(name, names)


if __name__ == "__main__":
    unittest.main()

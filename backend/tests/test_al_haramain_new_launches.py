"""Regression tests for verified Al Haramain new launches."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class AlHaramainNewLaunchTests(unittest.TestCase):
    def test_new_launches_have_official_product_page_evidence(self):
        expected = {
            "Haramain Camellia": ("https://shop.alharamainperfumes.com/eu/haramain-camellia.html", "Extrait de Parfum", None),
            "Amber Oud Smell Dubai": ("https://shop.alharamainperfumes.com/eu/haramain-amber-oud-smell-dubai-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Sameera": ("https://shop.alharamainperfumes.com/eu/haramain-sameera-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Empire Aromatique Ombre": ("https://shop.alharamainperfumes.com/eu/haramain-empire-aromatique-ombre-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Leif": ("https://shop.alharamainperfumes.com/eu/haramain-leif-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Harmony": ("https://shop.alharamainperfumes.com/eu/haramain-harmony-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "Freya": ("https://shop.alharamainperfumes.com/eu/haramain-freya-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            "L'Aventure Extreme": ("https://shop.alharamainperfumes.com/eu/haramain-l-aventure-extreme-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Amber Oud Gold Lux": ("https://shop.alharamainperfumes.com/default/haramain-amber-oud-gold-lux-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Sameera Noir": ("https://us.alharamainperfumes.com/en/haramain-sameera-noir-100ml-extrait-de-parfum.html", "Extrait de Parfum", 100),
            "Olaf": ("https://shop.alharamainperfumes.com/eu/haramain-olaf-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        "Avalon": ("https://shop.alharamainperfumes.com/eu/avalon-eau-de-parfum-100ml.html", "Eau de Parfum", 100),
        "Azure Mythique": ("https://shop.alharamainperfumes.com/eu/azure-mythique-eau-de-parfum-100ml.html", "Eau de Parfum", 100),
        "Cupuacu": ("https://shop.alharamainperfumes.com/eu/haramain-cupuacu-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        "Taj Malaki Noir": ("https://shop.alharamainperfumes.com/eu/haramain-taj-malaki-noir-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        "Gold Crystal Oudh": ("https://shop.alharamainperfumes.com/eu/haramain-gold-crystal-oudh-spray-100ml.html", "Extrait de Parfum", 100),
        "Gold Crystal Sapphire": ("https://shop.alharamainperfumes.com/eu/haramain-gold-crystal-sapphire-spray-100ml.html", "Extrait de Parfum", 100),
        "Acai": ("https://shop.alharamainperfumes.com/eu/haramain-acai-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        "Cacau": ("https://shop.alharamainperfumes.com/eu/haramain-cacau-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        "Caju": ("https://shop.alharamainperfumes.com/eu/haramain-caju-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
        }
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") in {"Al Haramain", "Al-Haramain", "Haramain"}
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
        for name in ("Haramain Camellia", "Amber Oud Smell Dubai", "Sameera", "Empire Aromatique Ombre", "Leif", "Sameera Noir", "Olaf"):
            self.assertIn(name, names)

    def test_al_haramain_ids_are_unique_and_variants_are_attached(self):
        products = [p for p in CATALOG["products"] if p.get("brand") in {"Al Haramain", "Al-Haramain", "Haramain"}]
        product_ids = [p["product_id"] for p in products]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        known = set(product_ids)
        self.assertTrue(all(v["product_id"] in known for v in CATALOG["variants"] if v["product_id"].startswith("SH-AL-HARAMAIN-")))


if __name__ == "__main__":
    unittest.main()

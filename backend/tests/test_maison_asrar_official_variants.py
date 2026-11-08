"""Official Maison Asrar source evidence for three 100 ml EDP variants."""
import json
import unittest
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Basma": ("SH-MAISON-ASRAR-a39f5b0c", "https://maisonasrar.com/products/maison-asrar-basma-eau-de-parfum-100-ml-unisex"),
    "Vanilla Rouge": ("SH-MAISON-ASRAR-02826afd", "https://maisonasrar.com/products/vanilla-rouge-maison-asrar-eau-de-perfum-100-ml"),
    "Petra": ("SH-MAISON-ASRAR-54c12160", "https://maisonasrar.com/products/petra-maison-asrar-eau-de-perfum-100ml"),
    "Soudfa": ("SH-MAISON-ASRAR-6210ceb2", "https://maisonasrar.com/products/maison-asrar-soudfa-eau-de-parfum-100-ml-for-women"),
    "Casablanca": ("SH-MAISON-ASRAR-ad855115", "https://maisonasrar.com/products/casablanca-maison-asrar-eau-de-perfum-100ml"),
    "Jawhara Rouge": ("SH-MAISON-ASRAR-d20dc7ce", "https://maisonasrar.com/collections/jawhara-collection/products/jawhara-rouge-eau-de-perfum-100ml"),
    "Jawhara Black": ("SH-MAISON-ASRAR-fce356db", "https://maisonasrar.com/products/jawhara-black-eau-de-perfum-100ml"),
    "Fresh Iris": ("SH-MAISON-ASRAR-f778e873", "https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml"),
}


class MaisonAsrarOfficialVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(CATALOG.read_text(encoding="utf-8"))
        cls.products = {p["canonical_name"]: p for p in cls.data["products"] if p.get("brand_name") == "Maison Asrar"}

    def test_eight_official_100ml_edp_variants(self):
        for name, (product_id, product_url) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["source_url"], product_url)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_evidence_url"], product_url)
                self.assertIn(100, product["formats_ml"])
                variants = [v for v in self.data["variants"] if v["product_id"] == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")

    def test_variant_ids_remain_unique(self):
        ids = [v["variant_id"] for v in self.data["variants"]]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()

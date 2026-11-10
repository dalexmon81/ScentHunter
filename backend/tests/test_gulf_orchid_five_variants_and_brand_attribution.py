"""Regression coverage for Gulf Orchid variants and Maison Asrar attribution."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = {
    "Al Qasr": {"id": "SH-GULF-ORCHID-4133b3ae", "size": 100, "url": "https://shop-gulforchid.com/products/al-qasr-silver"},
    "Tahara Vanilla Musk": {"id": "SH-GULF-ORCHID-TAHARA-VANILLA-MUSK", "size": 60, "url": "https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml"},
    "Exotic Oud": {"id": "SH-GULF-ORCHID-EXOTIC-OUD", "size": 100, "url": "https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum"},
    "Vanilla Latte": {"id": "SH-GULF-ORCHID-VANILLA-LATTE", "size": 100, "url": "https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum"},
    "Cookie Bite": {"id": "SH-GULF-ORCHID-COOKIE-BITE", "size": 100, "url": "https://shop-gulforchid.com/products/cookie-bite"},
    "Vanilla Aura": {"id": "SH-MAISON-ASRAR-bab16c06", "size": 100, "url": "https://shop-gulforchid.com/products/vanilla-aura"},
}

class GulfOrchidAndMaisonAsrarAttributionTests(unittest.TestCase):
    def test_six_official_variants_have_source_and_family_coverage(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("product_id") == expected["id"] and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                expected_brand = "Maison Asrar" if name == "Vanilla Aura" else "Gulf Orchid"
                self.assertEqual(product["brand"], expected_brand)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["concentration"], "Eau de Parfum")
                self.assertEqual(product["formats_ml"], [expected["size"]])
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == expected["id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], expected["size"])
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                self.assertNotIn("gtin", variants[0])
                family = next(f for f in REGISTRY["families"] if f.get("family_id") == product["family_id"])
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertIn(expected["size"], rows[0].get("formats_ml", []))

    def test_vanilla_voyage_is_attributed_to_maison_asrar_without_guessing_size(self):
        product = next(p for p in CATALOG["products"] if p.get("product_id") == "SH-MAISON-ASRAR-19d98178")
        self.assertEqual(product["canonical_name"], "Vanilla Voyage")
        self.assertEqual(product["brand"], "Maison Asrar")
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], "https://shop-gulforchid.com/products/maison-asrar-vanilla-voyage-eau-de-parfum")
        self.assertEqual(product["concentration"], "Eau de Parfum")
        self.assertNotIn("formats_ml", product)
        self.assertEqual([v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]], [])

    def test_misattributed_gulf_orchid_duplicates_are_removed(self):
        ids = {p.get("product_id") for p in CATALOG["products"]}
        self.assertNotIn("SH-GULF-ORCHID-2e9b4429", ids)
        self.assertNotIn("SH-GULF-ORCHID-0aca84c2", ids)
        gulf = next(f for f in REGISTRY["families"] if f.get("family_id") == "gulf_orchid_catalog")
        self.assertFalse(any(p.get("canonical_name") in {"Vanilla Aura", "Vanilla Voyage"} for p in gulf["products"]))

if __name__ == "__main__":
    unittest.main()

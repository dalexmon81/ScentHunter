"""Regression tests for Arabiyat Prestige official-store collection expansion."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Mahd Al Dhahab": (100, "Eau de Parfum"),
    "Nyla Sherbet": (80, "Eau de Parfum"),
    "Fahad Regal": (100, "Eau de Parfum"),
    "Aristo": (100, "Eau de Parfum"),
    "Bóis Blanc": (100, "Eau de Parfum"),
    "Cherry Musk": (100, "Eau de Parfum"),
    "Marasi For Her": (100, "Eau de Parfum"),
    "Marasi For Him": (100, "Eau de Parfum"),
    "Swar Serpentine": (100, "Eau de Parfum"),
    "Swar D'Amour": (100, "Eau de Parfum"),
    "Cursed": (100, "Eau de Parfum"),
    "Ramad Oriental": (100, "Eau de Parfum"),
    "Kohl Opulence": (100, "Eau de Parfum"),
    "Kohl Luminous": (100, "Eau de Parfum"),
    "Gelato Raspberry Ripple": (100, "Eau de Parfum"),
    "Gelato Black Current Lolly": (100, "Eau de Parfum"),
    "La Di Da For Her": (100, "Eau de Parfum"),
    "La Di Da For Him": (100, "Eau de Parfum"),
    "Uhud": (100, "Eau de Parfum"),
    "Safa": (100, "Eau de Parfum"),
}


class ArabiyatPrestigeOfficialStoreTests(unittest.TestCase):
    def test_expected_products_have_official_store_provenance(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "Arabiyat Prestige"
        }
        for name in EXPECTED:
            with self.subTest(name=name):
                self.assertIn(name, products)
                self.assertIn("eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/", products[name]["source_url"])
                self.assertEqual(products[name]["identity_status"], "source_verified_name")

    def test_explicit_size_and_concentration_variants_exist(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "Arabiyat Prestige"
        }
        for name, (size, concentration) in EXPECTED.items():
            with self.subTest(name=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == products[name]["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], size)
                self.assertEqual(variants[0]["concentration"], concentration)

    def test_family_registry_contains_each_added_identity_and_format(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "arabiyat_prestige_catalog")
        records = {p["canonical_name"]: p for p in family["products"]}
        for name, (size, _) in EXPECTED.items():
            with self.subTest(name=name):
                self.assertIn(name, records)
                self.assertIn(size, records[name]["formats_ml"])

    def test_product_ids_and_brand_name_pairs_are_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [
            (p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name"))
            for p in products
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))


if __name__ == "__main__":
    unittest.main()

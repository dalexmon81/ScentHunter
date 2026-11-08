"""Regression tests for the reconciled official Arabiyat Prestige product set."""
import json
import unittest
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

# Source, size and concentration are taken from the checked-in product-level
# verification overlay. Every expected item has its own official detail URL.
EXPECTED = {
    "Mahd Al Dhahab Extrait": (60, "Extrait de Parfum", "https://eu.myperfumes.ae/en-de/products/mahd-al-dhahab-extrait"),
    "Mahd Al Dhahab": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/mahd-al-dhahab"),
    "Nyla Sherbet": (80, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/nyla-sherbet"),
    "Fahad Regal": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/fahad-regal"),
    "Aristo": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/aristo"),
    "Bóis Blanc": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/bois-blanc"),
    "Cherry Musk": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/cherry-musk"),
    "Marasi For Her": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/marasi-for-her"),
    "Marasi For Him": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/marasi-for-him"),
    "Swar Serpentine": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/swar-serpentine"),
    "Swar D'Amour": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/swar-damour"),
    "Cursed": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/cursed"),
    "Ramad Oriental": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/ramad-oriental"),
    "Kohl Opulence": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/kohl-opulence"),
    "Kohl Luminous": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/kohl-luminous"),
    "Gelato Raspberry Ripple": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/raspberry-ripple"),
    "Gelato Black Currant Lolly": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/black-current-lolly"),
    "La Di Da For Her": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/la-di-da-for-her"),
    "La Di Da For Him": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/la-di-da-for-him"),
    "Uhud": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/uhud"),
    "Safa": (100, "Eau de Parfum", "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/safa"),
}

def norm(value):
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold().replace(" ", "").replace("-", "").replace("'", "")

class ArabiyatPrestigeOfficialStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in CATALOG["products"] if p.get("brand") == "Arabiyat Prestige"]
        cls.variants = CATALOG["variants"]
        cls.family = next(f for f in REGISTRY["families"] if f["family_id"] == "arabiyat_prestige_catalog")

    def product(self, name):
        matches = [p for p in self.products if norm(p["canonical_name"]) == norm(name) or any(norm(a) == norm(name) for a in p.get("aliases", []))]
        self.assertEqual(len(matches), 1, f"Expected exactly one canonical match for {name!r}")
        return matches[0]

    def test_each_official_product_has_exact_provenance(self):
        for name, (size, concentration, source) in EXPECTED.items():
            with self.subTest(name=name):
                product = self.product(name)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], source)

    def test_each_official_product_has_exact_variant(self):
        for name, (size, concentration, source) in EXPECTED.items():
            with self.subTest(name=name):
                product = self.product(name)
                matches = [v for v in self.variants if v.get("product_id") == product["product_id"] and v.get("size_ml") == size and v.get("concentration") == concentration]
                self.assertEqual(len(matches), 1)

    def test_family_registry_matches_verified_variant_formats(self):
        for name, (size, concentration, source) in EXPECTED.items():
            with self.subTest(name=name):
                product = self.product(name)
                matches = [f for f in self.family["products"] if norm(f["canonical_name"]) == norm(product["canonical_name"]) or any(norm(a) == norm(product["canonical_name"]) for a in f.get("aliases", []))]
                self.assertEqual(len(matches), 1)
                self.assertIn(size, matches[0].get("formats_ml", []))

    def test_catalog_product_and_variant_ids_remain_unique(self):
        products = CATALOG["products"]
        product_ids = [p["product_id"] for p in products]
        brand_names = [(p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name")) for p in products]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(brand_names), len(set(brand_names)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

if __name__ == "__main__":
    unittest.main()

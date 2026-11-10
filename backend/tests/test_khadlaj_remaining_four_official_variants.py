"""Regression checks for the four remaining Khadlaj official product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Panache Eleganza": ("SH-KHADLAJ-c0a0f7d9", 100, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/panache-eleganza-100-ml-extrait-de-parfum-spray-for-women", "6298043070812"),
    "Oud Noir": ("SH-KHADLAJ-SPRAY-HARVEST-104", 100, "Eau de Parfum", "https://khadlaj-perfumes.com/collections/ombre-range/products/oud-noir-100ml-spray-shop-online-best-price-in-dubai-uae", None),
    "Ombre Notes": ("SH-KHADLAJ-SPRAY-HARVEST-106", 100, "Eau de Parfum", "https://khadlaj-perfumes.com/collections/deals/products/ombre-notes-edp-spray-shop-online-best-price-in-dubai-uae", None),
    "Infini": ("SH-KHADLAJ-SPRAY-HARVEST-112", 100, "Eau de Parfum", "https://khadlaj-perfumes.com/collections/perfumes-spray/products/infini-edp-spray-spray-shop-online-best-price-in-dubai-uae", "6297000742625"),
}

class KhadlajRemainingFourOfficialVariantsTests(unittest.TestCase):
    def test_existing_canonical_identities_are_verified(self):
        for name, (product_id, size, concentration, url, gtin) in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in CATALOG["products"] if p.get("product_id") == product_id and p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["concentration"], concentration)
                self.assertEqual(product["formats_ml"], [size])
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], size)
                self.assertEqual(variants[0]["concentration"], concentration)
                self.assertEqual(variants[0].get("gtin"), gtin)

    def test_family_registry_is_aligned(self):
        for name, (product_id, size, concentration, url, gtin) in EXPECTED.items():
            product = next(p for p in CATALOG["products"] if p.get("product_id") == product_id)
            family = next(f for f in REGISTRY["families"] if f.get("family_id") == product["family_id"])
            rows = [p for p in family["products"] if p.get("canonical_name") == name]
            self.assertEqual(len(rows), 1)
            self.assertIn(size, rows[0].get("formats_ml", []))

    def test_no_duplicate_product_or_variant_ids(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

if __name__ == "__main__":
    unittest.main()

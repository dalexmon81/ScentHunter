"""Regression coverage for Maison Asrar official perfume detail pages."""
import json
import unittest
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Bloom Bloom": ("https://maisonasrar.com/products/bloom-bloom-eau-de-parfum-100ml", 100),
    "Lolita": ("https://maisonasrar.com/products/lolita-eau-de-parfum-100ml", 100),
    "Bonita": ("https://maisonasrar.com/products/bonita-eau-de-parfum-100ml", 100),
    "Lily": ("https://maisonasrar.com/products/lily-eau-de-parfum-100ml", 100),
    "Kiss My Lips": ("https://maisonasrar.com/products/kiss-my-lips-maison-asrar-eau-de-perfum-90ml", 90),
    "Never Forget Me": ("https://maisonasrar.com/products/never-forget-me-maison-asrar-eau-de-perfum-90ml", 90),
    "Night in Paris": ("https://maisonasrar.com/products/night-in-paris-maison-asrar-eau-de-perfum-90ml", 90),
    "Sunset in Capri": ("https://maisonasrar.com/products/sunset-in-capri-maison-asrar-eau-de-perfum-90ml", 90),
    "Dear Jasmine": ("https://maisonasrar.com/products/dear-jasmine-maison-asrar-eau-de-perfum-100-ml", 100),
    "Patchouli with Love": ("https://maisonasrar.com/products/patchouli-with-love-maison-asrar-eau-de-perfum-100-ml", 100),
    "Fresh Iris": ("https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml", 100),
    "Vanilla Rouge": ("https://maisonasrar.com/products/vanilla-rouge-maison-asrar-eau-de-perfum-100-ml", 100),
}

class MaisonAsrarOfficialPerfumeDetailsTests(unittest.TestCase):
    def test_existing_identities_have_official_detail_and_exact_variant(self):
        for name, (url, size) in EXPECTED.items():
            with self.subTest(name=name):
                matches = [p for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) == "Maison Asrar" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                p = matches[0]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["source_evidence_url"], url)
                self.assertEqual(p["concentration"], "Eau de Parfum")
                self.assertIn(size, p["formats_ml"])
                variants = [v for v in CATALOG["variants"] if v["product_id"] == p["product_id"] and v["size_ml"] == size]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["concentration"], "Eau de Parfum")
                self.assertEqual(variants[0]["source_url"], url)

    def test_no_commercial_offer_fields_added(self):
        ids = {p["product_id"] for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) == "Maison Asrar"}
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url"}
        for item in CATALOG["products"] + CATALOG["variants"]:
            if item.get("product_id") in ids:
                self.assertTrue(forbidden.isdisjoint(item))

    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

if __name__ == "__main__":
    unittest.main()

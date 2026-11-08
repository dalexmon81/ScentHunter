"""Regression tests for individually verified November 2026 fragrance additions."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class VerifiedNewFragranceAdditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            (row.get("brand_name") or row.get("brand"), row.get("canonical_name") or row.get("name")): row
            for row in CATALOG.get("products", [])
        }
        cls.variants = CATALOG.get("variants", [])

    def variants_for(self, product):
        return [row for row in self.variants if row.get("product_id") == product["product_id"]]

    def test_lattafa_asad_polar_official_identity_and_size(self):
        row = self.products[("Lattafa", "Asad Polar")]
        self.assertEqual(row["identity_status"], "source_verified_name")
        self.assertEqual(row["source_url"], "https://lattafa.com/product/asad-polar/")
        self.assertNotIn("concentration", row)
        variants = self.variants_for(row)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["size_ml"], 100)
        self.assertNotIn("concentration", variants[0])

    def test_bujairami_full_effect_official_detail_page(self):
        row = self.products[("Bujairami", "Full Effect")]
        self.assertEqual(row["identity_status"], "source_verified_name")
        self.assertEqual(
            row["source_url"],
            "https://bujairami.com.au/products/full-effect-inspired-by-mezzo-sospiro-perfumes",
        )
        # The official detail page reviewed for this addition does not state
        # a bottle size or concentration, so neither is inferred.
        self.assertNotIn("concentration", row)
        self.assertEqual(self.variants_for(row), [])

    def test_khadlaj_panache_eleganza_has_official_100ml_extrait_variant(self):
        row = self.products[("Khadlaj", "Panache Eleganza")]
        self.assertEqual(row["identity_status"], "source_verified_name")
        self.assertEqual(
            row["source_url"],
            "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/panache-eleganza-100-ml-extrait-de-parfum-spray-for-women",
        )
        variants = self.variants_for(row)
        self.assertTrue(any(
            item.get("size_ml") == 100 and item.get("concentration") == "Extrait de Parfum"
            for item in variants
        ))

    def test_khadlaj_sueno_has_official_100ml_extrait_variant(self):
        row = self.products[("Khadlaj", "Sueno")]
        self.assertEqual(
            row["source_url"],
            "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/sueno-100ml-extrait-de-parfum-for-women",
        )
        variants = self.variants_for(row)
        self.assertTrue(any(
            item.get("size_ml") == 100 and item.get("concentration") == "Extrait de Parfum"
            for item in variants
        ))

    def test_product_and_variant_ids_remain_unique(self):
        product_ids = [row["product_id"] for row in CATALOG.get("products", [])]
        variant_ids = [row["variant_id"] for row in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()

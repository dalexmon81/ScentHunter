"""Official-source regression for Khadlaj Shiyaaka Rose Gold.

The official Kuwait product page supplies the exact 100 ml EDP name and GTIN.
This test protects the existing canonical product and variant IDs.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DETAIL_URL = "https://kw.khadlaj-perfumes.com/products/shiyaaka-for-women-spray-shop-online-best-price-in-dubai-uae"
PRODUCT_ID = "SH-KHADLAJ-afe1f6d4"
VARIANT_ID = "SHV-SH-KHADLAJ-afe1f6d4-100-000"
GTIN = "6291107971186"


class KhadlajShiyaakaRoseGoldOfficialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
        cls.registry = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

    def test_existing_canonical_product_is_verified_without_new_identity(self):
        rows = [p for p in self.catalog["products"] if p.get("product_id") == PRODUCT_ID]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.get("brand_name"), "Khadlaj")
        self.assertEqual(row.get("canonical_name"), "Shiyaaka Rose Gold")
        self.assertEqual(row.get("identity_status"), "source_verified_name")
        self.assertEqual(row.get("source_url"), DETAIL_URL)
        self.assertEqual(row.get("formats_ml"), [100])
        self.assertEqual(row.get("concentration"), "Eau de Parfum")

    def test_existing_variant_is_enriched_and_gtin_is_unique(self):
        rows = [
            v for v in self.catalog["variants"]
            if v.get("variant_id") == VARIANT_ID
        ]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.get("product_id"), PRODUCT_ID)
        self.assertEqual(row.get("size_ml"), 100)
        self.assertEqual(row.get("concentration"), "Eau de Parfum")
        self.assertEqual(row.get("gtin"), GTIN)
        self.assertEqual(row.get("source_evidence_url"), DETAIL_URL)
        self.assertEqual(
            sum(1 for v in self.catalog["variants"] if v.get("gtin") == GTIN),
            1,
        )

    def test_family_registry_matches_existing_canonical_identity(self):
        family = next(f for f in self.registry["families"] if f.get("family_id") == "khadlaj_shiyaaka")
        rows = [p for p in family.get("products", []) if p.get("canonical_name") == "Shiyaaka Rose Gold"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("formats_ml"), [100])

    def test_no_duplicate_product_or_variant_ids_or_orphan_variants(self):
        products = self.catalog["products"]
        variants = self.catalog["variants"]
        product_ids = [p.get("product_id") for p in products]
        variant_ids = [v.get("variant_id") for v in variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        known = set(product_ids)
        self.assertTrue(all(v.get("product_id") in known for v in variants))


if __name__ == "__main__":
    unittest.main()

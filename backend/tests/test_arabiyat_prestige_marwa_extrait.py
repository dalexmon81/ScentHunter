"""Regression tests for the official Arabiyat Prestige Marwa Extrait identity."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
GTIN_MAP = json.loads((BACKEND / "scenthunter_next_engine/verified_gtin_variant_map.json").read_text(encoding="utf-8"))

BRAND = "Arabiyat Prestige"
NAME = "Marwa Extrait"
PRODUCT_ID = "SH-ARABIYAT-PRESTIGE-MARWA-EXTRAIT-6295156402103"
VARIANT_ID = "SHV-SH-ARABIYAT-PRESTIGE-MARWA-EXTRAIT-6295156402103-60-000"
SOURCE = "https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/marwa-extrait"
GTIN = "6295156402103"


class ArabiyatPrestigeMarwaExtraitTests(unittest.TestCase):
    def test_canonical_identity_is_unique_and_source_verified(self):
        matches = [p for p in CATALOG["products"] if p.get("brand") == BRAND and p.get("canonical_name") == NAME]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["product_id"], PRODUCT_ID)
        self.assertEqual(matches[0]["identity_status"], "source_verified_name")
        self.assertEqual(matches[0]["source_url"], SOURCE)

    def test_60ml_extrait_variant_is_distinct_from_marwa_edp(self):
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == PRODUCT_ID]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["variant_id"], VARIANT_ID)
        self.assertEqual(variants[0]["size_ml"], 60)
        self.assertEqual(variants[0]["concentration"], "Extrait de Parfum")
        marwa = next(p for p in CATALOG["products"] if p.get("brand") == BRAND and p.get("canonical_name") == "Marwa")
        self.assertNotEqual(marwa["product_id"], PRODUCT_ID)

    def test_registry_contains_identity_and_format(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "arabiyat_prestige_catalog")
        record = next(p for p in family["products"] if p["canonical_name"] == NAME)
        self.assertEqual(record["formats_ml"], [60])

    def test_verified_gtin_targets_exact_variant(self):
        records = [r for r in GTIN_MAP["records"] if r["gtin"] == GTIN]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "verified")
        self.assertEqual(records[0]["product_id"], PRODUCT_ID)
        self.assertEqual(records[0]["variant_id"], VARIANT_ID)
        self.assertEqual(records[0]["size_ml"], 60)
        self.assertEqual(records[0]["concentration"], "Extrait de Parfum")

    def test_catalog_product_ids_and_brand_name_pairs_remain_unique(self):
        products = CATALOG["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand") or p.get("brand_name"), p.get("canonical_name") or p.get("name")) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))


if __name__ == "__main__":
    unittest.main()

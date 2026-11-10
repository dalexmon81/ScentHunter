"""Global duplicate/orphan guards for the integrated canonical catalog."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class IntegratedCatalogIntegrityTests(unittest.TestCase):
    def test_product_ids_are_unique(self):
        ids = [p["product_id"] for p in CATALOG["products"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_variant_ids_are_unique(self):
        ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_orphan_variants(self):
        products = {p["product_id"] for p in CATALOG["products"]}
        self.assertTrue(all(v["product_id"] in products for v in CATALOG["variants"]))

    def test_no_duplicate_product_size_pairs(self):
        pairs = [(v["product_id"], v["size_ml"]) for v in CATALOG["variants"]]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_no_offer_fields_in_canonical_variants(self):
        forbidden = {"price", "stock", "shipping_cost", "store_url", "availability"}
        for variant in CATALOG["variants"]:
            with self.subTest(variant_id=variant.get("variant_id")):
                self.assertFalse(forbidden.intersection(variant))

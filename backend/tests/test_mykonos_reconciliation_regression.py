"""Regression tests for the reconciled Mykonos catalog snapshot."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
MYKONOS = [p for p in CATALOG.get("products", []) if p.get("brand_name") == "Mykonos"]
MYKONOS_IDS = {p["product_id"] for p in MYKONOS}
VARIANTS = [v for v in CATALOG.get("variants", []) if v.get("product_id") in MYKONOS_IDS]


class MykonosReconciliationTests(unittest.TestCase):
    def test_expected_identity_and_variant_counts(self):
        self.assertEqual(len(MYKONOS), 99)
        self.assertEqual(len(VARIANTS), 102)

    def test_all_identities_have_source_and_status(self):
        for product in MYKONOS:
            with self.subTest(name=product.get("canonical_name")):
                self.assertTrue(product.get("source_url"))
                self.assertIn(product.get("identity_status"), {"source_verified_name", "source_listed_name"})

    def test_official_15ml_travel_page_supports_18_distinct_variants(self):
        source = "https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml"
        expected = {
            "Dark Secret", "Musk Aura", "Sansa", "Satin Blanc", "Sparkling Rosé",
            "Black Opera", "Moroccan Vanilla", "Affair", "Utopia", "Tea Poetry",
            "Hawaiian Crush", "On The Rocks", "Royal Ispahan", "Crimson",
            "California", "California Blue", "Penthouse", "Monaco Royale",
        }
        by_id = {p["product_id"]: p for p in MYKONOS}
        travel = [v for v in VARIANTS if v.get("size_ml") == 15 and v.get("source_evidence_url") == source]
        self.assertEqual(len(travel), 18)
        self.assertEqual({by_id[v["product_id"]]["canonical_name"] for v in travel}, expected)

    def test_empire_and_imperium_are_distinct(self):
        products = {p["canonical_name"]: p for p in MYKONOS}
        self.assertIn("Empire x RRQ", products)
        self.assertIn("Imperium", products)
        self.assertNotEqual(products["Empire x RRQ"]["product_id"], products["Imperium"]["product_id"])
        self.assertNotIn("Imperium", products["Empire x RRQ"].get("aliases", []))
        self.assertEqual(
            products["Empire x RRQ"].get("source_evidence_url"),
            products["Empire x RRQ"].get("source_url"),
        )

    def test_no_duplicate_ids_or_orphan_variants(self):
        all_products = CATALOG.get("products", [])
        all_variants = CATALOG.get("variants", [])
        self.assertEqual(len({p["product_id"] for p in all_products}), len(all_products))
        self.assertEqual(len({v["variant_id"] for v in all_variants}), len(all_variants))
        product_ids = {p["product_id"] for p in all_products}
        self.assertTrue(all(v["product_id"] in product_ids for v in all_variants))


if __name__ == "__main__":
    unittest.main()

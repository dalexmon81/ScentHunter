"""Afnan fourth evidence batch: three existing identities upgraded from official detail pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Supremacy Not Only Intense": {
        "url": "https://it.afnan.com/products/supremacy-not-only-intense",
        "concentration": "Extrait de Parfum",
        "sizes": {100, 150},
    },
    "Turathi Electric": {
        "url": "https://www.at.afnan.com/en/products/turathi-electric",
        "concentration": "Eau de Parfum",
        "sizes": {90},
    },
    "Kiaana Crush": {
        "url": "https://us.afnan.com/products/kiaana-crush",
        "concentration": "Eau de Parfum",
        "sizes": {100},
    },
}

class AfnanOfficialEvidenceFourthBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(x for x in REGISTRY["families"] if x.get("family_id") == "afnan_catalog")

    def test_official_detail_page_evidence_and_existing_identity_reuse(self):
        for name, spec in EXPECTED.items():
            with self.subTest(name=name):
                rows = [p for p in self.products if p.get("brand_name") == "Afnan"
                        and (p.get("canonical_name") or p.get("name", "")).casefold() == name.casefold()]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["concentration"], spec["concentration"])
                self.assertEqual(set(product["formats_ml"]), spec["sizes"])
                self.assertEqual(product["source_url"], spec["url"])
                self.assertEqual(product["source_evidence_url"], spec["url"])
                self.assertEqual(product["source_product_url"], spec["url"])
                variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual({v["size_ml"] for v in variants}, spec["sizes"])
                for variant in variants:
                    self.assertEqual(variant["concentration"], spec["concentration"])
                    self.assertEqual(variant["source_evidence_url"], spec["url"])
                    self.assertNotIn("gtin", variant)
                family_rows = [x for x in self.family["products"]
                               if x.get("canonical_name", "").casefold() == name.casefold()]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(set(family_rows[0]["formats_ml"]), spec["sizes"])

    def test_catalog_integrity_and_offer_data_separation(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        variant_tuples = [(v.get("product_id"), v.get("size_ml"), v.get("concentration")) for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(variant_tuples), len(set(variant_tuples)))
        known_products = set(product_ids)
        self.assertTrue(all(v.get("product_id") in known_products for v in self.variants))
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        self.assertTrue(all(forbidden.isdisjoint(v) for v in self.variants))

if __name__ == "__main__":
    unittest.main()

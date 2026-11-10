"""Afnan third evidence batch: five official EDP variants across four existing identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "9 PM Pour Femme": {100: "https://afnan.com/products/9-pm-pour-femme"},
    "Supremacy Silver": {
        100: "https://afnan.com/products/supremacy-silver",
        150: "https://afnan.com/products/supremacy-silver",
    },
    "Turathi Purple": {90: "https://de.afnan.com/products/turathi-purple-femme"},
    "TURATHI RED": {90: "https://saudi.afnan.com/products/turathi-red-femme"},
}

class AfnanOfficialEvidenceThirdBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(x for x in REGISTRY["families"] if x.get("family_id") == "afnan_catalog")

    def product(self, name):
        rows = [p for p in self.products if p.get("brand_name") == "Afnan" and
                (p.get("canonical_name") or p.get("name", "")).casefold() == name.casefold()]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_official_variants_and_existing_identity_reuse(self):
        for name, sizes in EXPECTED.items():
            with self.subTest(name=name):
                p = self.product(name)
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["concentration"], "Eau de Parfum")
                self.assertEqual(sorted(p["formats_ml"]), sorted(sizes))
                self.assertEqual(p["source_url"], next(iter(sizes.values())))
                self.assertEqual(p["source_evidence_url"], next(iter(sizes.values())))
                self.assertEqual(p["source_product_url"], next(iter(sizes.values())))
                rows = [v for v in self.variants if v.get("product_id") == p["product_id"]]
                self.assertEqual({v["size_ml"] for v in rows}, set(sizes))
                for v in rows:
                    url = sizes[v["size_ml"]]
                    self.assertEqual(v["variant_id"], f"SHV-{p['product_id']}-{v['size_ml']}-EDP")
                    self.assertEqual(v["concentration"], "Eau de Parfum")
                    self.assertEqual(v["source_evidence_url"], url)
                    self.assertNotIn("gtin", v)
                family_rows = [x for x in self.family["products"]
                               if x.get("canonical_name", "").casefold() == name.casefold()]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0]["formats_ml"], sorted(sizes))

    def test_global_uniqueness_orphans_and_offer_separation(self):
        pids = [p.get("product_id") for p in self.products]
        vids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        tuples = [(v.get("product_id"), v.get("size_ml"), v.get("concentration")) for v in self.variants]
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(vids), len(set(vids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        known = set(pids)
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        self.assertTrue(all(forbidden.isdisjoint(v) for v in self.variants))

if __name__ == "__main__":
    unittest.main()

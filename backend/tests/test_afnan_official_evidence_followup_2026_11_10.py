"""Afnan follow-up: seven page-backed variants plus three name-only verifications."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

VARIANTS = {
    "Portrait Revival": (100, "https://afnan.com/products/portrait-revival"),
    "Rare Passion": (100, "https://afnan.com/products/rare-passion"),
    "Souvenir Blooming Bliss": (100, "https://afnan.com/products/souvenir-blooming-bliss"),
    "Souvenir Desert Rose": (100, "https://afnan.com/products/souvenir-desert-rose"),
    "SUPREMACY TAPIS ROUGE - LUXURY COLLECTION": (90, "https://afnan.com/products/supremacy-tapis-rouge"),
    "Tribute Pink": (100, "https://afnan.com/products/tribute-pink"),
    "Violet Bouquet": (80, "https://afnan.com/products/violet-bouquet"),
}
IDENTITY_ONLY = {
    "Inara White": "https://afnan.com/products/inara-white",
    "Modest Une": "https://afnan.com/products/modest-une",
    "Paris Oud": "https://afnan.com/products/paris-oud",
}

class AfnanOfficialEvidenceFollowupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(x for x in REGISTRY["families"] if x.get("family_id") == "afnan_catalog")

    def product(self, name):
        rows = [p for p in self.products if p.get("brand_name") == "Afnan" and (p.get("canonical_name") or p.get("name", "")).casefold() == name.casefold()]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_official_detail_variants(self):
        for name, (size, url) in VARIANTS.items():
            with self.subTest(name=name):
                p = self.product(name)
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["source_evidence_url"], url)
                self.assertEqual(p["source_product_url"], url)
                self.assertEqual(p["concentration"], "Eau de Parfum")
                self.assertEqual(p["formats_ml"], [size])
                rows = [v for v in self.variants if v.get("product_id") == p["product_id"]]
                self.assertEqual(len(rows), 1)
                v = rows[0]
                self.assertEqual(v["variant_id"], f"SHV-{p['product_id']}-{size}-EDP")
                self.assertEqual(v["size_ml"], size)
                self.assertEqual(v["concentration"], "Eau de Parfum")
                self.assertEqual(v["source_evidence_url"], url)
                self.assertNotIn("gtin", v)
                fr = [x for x in self.family["products"] if x.get("canonical_name", "").casefold() == name.casefold()]
                self.assertEqual(len(fr), 1)
                self.assertEqual(fr[0].get("formats_ml"), [size])

    def test_identity_only_pages_do_not_create_guessed_variants(self):
        for name, url in IDENTITY_ONLY.items():
            with self.subTest(name=name):
                p = self.product(name)
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["source_product_url"], url)
                self.assertFalse(any(v.get("product_id") == p["product_id"] for v in self.variants))
                self.assertNotIn("formats_ml", p)
                fr = next(x for x in self.family["products"] if x.get("canonical_name", "").casefold() == name.casefold())
                self.assertNotIn("formats_ml", fr)

    def test_catalog_integrity_and_offer_separation(self):
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

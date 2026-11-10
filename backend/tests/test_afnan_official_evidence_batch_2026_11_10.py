"""Eight additional Afnan variants verified from individual official product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Cherry Bouquet": (80, "https://afnan.com/products/cherry-bouquet"),
    "Historic Doria": (100, "https://afnan.com/products/historic-doria"),
    "LA FLEUR BOUQUET": (80, "https://afnan.com/products/la-fleur-bouquet"),
    "ORNAMENT POUR FEMME": (100, "https://afnan.com/products/ornament-pour-femme"),
    "Ornament Purple": (100, "https://afnan.com/products/ornament-purple"),
    "Portrait Abstract": (100, "https://afnan.com/products/portrait-abstract"),
    "Supremacy in Heaven": (100, "https://afnan.com/products/supremacy-in-heaven"),
    "Tribute Blue": (100, "https://afnan.com/products/tribute-blue"),
}

class AfnanOfficialEvidenceBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(x for x in REGISTRY["families"] if x.get("family_id") == "afnan_catalog")

    def test_each_official_page_backed_variant_and_existing_identity(self):
        for name, (size_ml, url) in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in self.products if p.get("brand_name") == "Afnan" and (p.get("canonical_name") or p.get("name", "")).casefold() == name.casefold()]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertTrue(product["product_id"].startswith("SH-AFNAN-"))
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["concentration"], "Eau de Parfum")
                self.assertEqual(product["formats_ml"], [size_ml])
                matching = [v for v in self.variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(matching), 1)
                variant = matching[0]
                self.assertEqual(variant["variant_id"], f"SHV-{product['product_id']}-{size_ml}-EDP")
                self.assertEqual(variant["size_ml"], size_ml)
                self.assertEqual(variant["concentration"], "Eau de Parfum")
                self.assertEqual(variant["source_evidence_url"], url)
                self.assertNotIn("gtin", variant)

    def test_family_registry_formats_are_synchronized(self):
        for name, (size_ml, _) in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in self.family["products"] if p.get("canonical_name", "").casefold() == name.casefold()]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [size_ml])

    def test_global_identity_variant_and_offer_invariants(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        tuples = [(v.get("product_id"), v.get("size_ml"), v.get("concentration")) for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        known = set(product_ids)
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        for variant in self.variants:
            self.assertTrue(forbidden.isdisjoint(variant))

if __name__ == "__main__":
    unittest.main()

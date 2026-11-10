"""Regression checks for official catalog records recovered from older draft branches."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

class RecoveredOfficialCatalogRecordsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_marwa_variant_is_restored_from_current_official_page(self):
        product = next(p for p in self.products if p.get("product_id") == "SH-ARABIYAT-PRESTIGE-7bf3b46e")
        url = "https://arabiyatprestige.com/products/arabiyat-prestige-marwa-edp-100ml-unisex"
        self.assertEqual(product["brand"], "Arabiyat Prestige")
        self.assertEqual(product["canonical_name"], "Marwa")
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], url)
        self.assertEqual(product["source_product_url"], url)
        self.assertEqual(product["source_evidence_url"], url)
        self.assertEqual(product["formats_ml"], [100])
        self.assertEqual(product["concentration"], "Eau de Parfum")
        self.assertEqual(product["gender"], "Unisex")
        variant = next(v for v in self.variants if v.get("variant_id") == "SHV-SH-ARABIYAT-PRESTIGE-7bf3b46e-100-EDP")
        self.assertEqual(variant["product_id"], product["product_id"])
        self.assertEqual(variant["size_ml"], 100)
        self.assertEqual(variant["concentration"], "Eau de Parfum")
        self.assertEqual(variant["gender"], "Unisex")
        self.assertEqual(variant["source_url"], url)
        self.assertEqual(variant["source_evidence_url"], url)
        self.assertNotIn("gtin", variant)
        family = self.families[product["family_id"]]
        row = next(p for p in family["products"] if p.get("canonical_name") == "Marwa")
        self.assertEqual(row.get("formats_ml"), [100])

    def test_kismet_legacy_variant_is_superseded_not_duplicated(self):
        product = next(p for p in self.products if p.get("product_id") == "SH-MAISON-ALHAMBRA-dd2c5772")
        self.assertEqual(product["canonical_name"], "Kismet for Men")
        self.assertEqual(product.get("gtins"), ["6291107459257"])
        variants = [v for v in self.variants if v.get("product_id") == product["product_id"]]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["variant_id"], "SHV-SH-MAISON-ALHAMBRA-dd2c5772-100-MEN")
        self.assertEqual(variants[0].get("gtin"), "6291107459257")
        self.assertNotIn(
            "SHV-SH-MAISON-ALHAMBRA-dd2c5772-100-000",
            [v.get("variant_id") for v in self.variants],
        )

    def test_gulf_orchid_duplicate_attributions_are_not_reintroduced(self):
        product_ids = {p.get("product_id") for p in self.products}
        self.assertNotIn("SH-GULF-ORCHID-2e9b4429", product_ids)
        self.assertNotIn("SH-GULF-ORCHID-0aca84c2", product_ids)
        vanilla_aura = next(p for p in self.products if p.get("product_id") == "SH-MAISON-ASRAR-bab16c06")
        vanilla_voyage = next(p for p in self.products if p.get("product_id") == "SH-MAISON-ASRAR-19d98178")
        self.assertEqual(vanilla_aura["brand"], "Maison Asrar")
        self.assertEqual(vanilla_voyage["brand"], "Maison Asrar")

    def test_global_catalog_integrity_and_offer_separation(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        tuples = [(v.get("product_id"), v.get("size_ml"), v.get("concentration")) for v in self.variants]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        self.assertTrue(all(v.get("product_id") in known_products for v in self.variants))
        forbidden = {"price", "price_eur", "stock", "availability", "shipping_cost", "store_url", "retailer_url", "offer_url", "merchant"}
        for variant in self.variants:
            self.assertTrue(forbidden.isdisjoint(variant.keys()))


if __name__ == "__main__":
    unittest.main()

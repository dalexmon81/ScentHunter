"""Official Velixir detail pages: eight existing identities, sixteen explicit EDP sizes."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "SH-VELIXIR-ebb650c6": ("Adonis", "https://velixirparfums.com/products/adonis"),
    "SH-VELIXIR-6b018fb1": ("Apollo", "https://velixirparfums.com/products/apollo"),
    "SH-VELIXIR-599e6e9d": ("Ares", "https://velixirparfums.com/products/ares"),
    "SH-VELIXIR-7a65a419": ("Athena", "https://velixirparfums.com/products/athena"),
    "SH-VELIXIR-1089d534": ("Helios", "https://velixirparfums.com/products/helios"),
    "SH-VELIXIR-23a9f320": ("Narcisus", "https://velixirparfums.com/products/narcisus"),
    "SH-VELIXIR-cfe48ddb": ("Orion", "https://velixirparfums.com/products/orion"),
    "SH-VELIXIR-8c915ae1": ("Paladin", "https://velixirparfums.com/products/paladin"),
}


class VelixirRemainingEightOfficialVariantsTests(unittest.TestCase):
    def test_existing_canonical_ids_get_exactly_two_official_edp_variants(self):
        products = {p["product_id"]: p for p in CATALOG["products"]}
        variants = CATALOG["variants"]
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "velixir_catalog")
        family_rows = {p["canonical_name"]: p for p in family["products"]}

        for product_id, (name, url) in EXPECTED.items():
            with self.subTest(product=name):
                product = products[product_id]
                self.assertEqual(product["canonical_name"], name)
                self.assertEqual(product["brand"], "Velixir")
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["formats_ml"], [35, 100])
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(family_rows[name]["formats_ml"], [35, 100])
                rows = [v for v in variants if v["product_id"] == product_id]
                self.assertEqual({v["size_ml"] for v in rows}, {35, 100})
                self.assertEqual({v["concentration"] for v in rows}, {"Eau de Parfum"})
                self.assertEqual({v["source_url"] for v in rows}, {url})
                self.assertEqual({v["source_evidence_url"] for v in rows}, {url})
                self.assertEqual(
                    {v["variant_id"] for v in rows},
                    {f"SHV-{product_id}-35-EDP", f"SHV-{product_id}-100-EDP"},
                )
                self.assertTrue(all(not v.get("gtin") for v in rows))

    def test_global_catalog_and_registry_integrity(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        product_ids = [p["product_id"] for p in products]
        variant_ids = [v["variant_id"] for v in variants]
        gtins = [v["gtin"] for v in variants if v.get("gtin")]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        known = set(product_ids)
        self.assertTrue(all(v["product_id"] in known for v in variants))
        tuples = [(v["product_id"], v["size_ml"], v.get("concentration")) for v in variants]
        self.assertEqual(len(tuples), len(set(tuples)))
        forbidden = {"price", "price_amount", "currency", "availability", "stock",
                     "shipping_cost", "offer_url", "retailer", "store_id"}
        self.assertTrue(all(not forbidden.intersection(v) for v in variants))


if __name__ == "__main__":
    unittest.main()

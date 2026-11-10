"""Protect the officially verified 35 ml Khadlaj concentrated-oil variant."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PRODUCT_ID = "SH-KHADLAJ-f492c4b4"
VARIANT_ID = "SHV-SH-KHADLAJ-f492c4b4-35-000"
OFFICIAL_URL = "https://khadlaj-perfumes.com/products/hareem-al-sultan-gold-35ml"


class KhadlajHareemAlSultanGoldOilTests(unittest.TestCase):
    def test_existing_identity_and_35ml_concentrated_oil_variant(self):
        products = [p for p in CATALOG["products"] if p.get("product_id") == PRODUCT_ID]
        variants = [v for v in CATALOG["variants"] if v.get("variant_id") == VARIANT_ID]
        self.assertEqual(len(products), 1)
        self.assertEqual(len(variants), 1)

        product, variant = products[0], variants[0]
        self.assertEqual(product.get("canonical_name"), "Hareem Al Sultan Gold")
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("formats_ml"), [35])
        self.assertEqual(product.get("concentration"), "Concentrated Oil")
        self.assertEqual(variant.get("product_id"), PRODUCT_ID)
        self.assertEqual(variant.get("size_ml"), 35)
        self.assertEqual(variant.get("concentration"), "Concentrated Oil")
        self.assertEqual(product.get("source_url"), OFFICIAL_URL)
        self.assertEqual(product.get("source_product_url"), OFFICIAL_URL)
        self.assertEqual(product.get("source_evidence_url"), OFFICIAL_URL)
        self.assertEqual(variant.get("source_url"), OFFICIAL_URL)
        self.assertEqual(variant.get("source_evidence_url"), OFFICIAL_URL)

    def test_family_registry_still_maps_existing_canonical_product(self):
        product = next(p for p in CATALOG["products"] if p.get("product_id") == PRODUCT_ID)
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == product["family_id"])
        rows = [p for p in family["products"] if p.get("canonical_name") == "Hareem Al Sultan Gold"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get("formats_ml"), [35])

    def test_global_catalog_identity_and_offer_separation(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        product_ids = [p["product_id"] for p in products]
        variant_ids = [v["variant_id"] for v in variants]
        gtins = [v["gtin"] for v in variants if v.get("gtin")]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        known_products = set(product_ids)
        self.assertTrue(all(v["product_id"] in known_products for v in variants))
        commercial_fields = {
            "price", "price_eur", "stock", "availability", "shipping_cost",
            "store_url", "retailer_url", "offer_url", "merchant",
        }
        self.assertTrue(all(commercial_fields.isdisjoint(v) for v in variants))


if __name__ == "__main__":
    unittest.main()

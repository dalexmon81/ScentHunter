"""Official Assaf detail evidence for Wild Colt and Alex Enable variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Wild Colt": {
        "product_id": "SH-ASSAF-05c40179",
        "source": "https://assaf.ae/products/wild-colt-125-ml",
        "gender": "Unisex",
        "variants": {
            125: "https://assaf.ae/products/wild-colt-125-ml",
        },
    },
    "Alex Enable": {
        "product_id": "SH-ASSAF-342a7ff8",
        "source": "https://assaf.ae/products/alex-enable",
        "gender": "Men",
        "variants": {
            100: "https://assaf.ae/products/alex-enable",
            150: "https://assaf.ae/products/alex-enable-150ml",
        },
    },
}


class AssafWildColtAlexEnableOfficialVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_existing_canonical_ids_are_promoted_with_first_party_evidence(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [
                    p for p in self.products
                    if p.get("brand_name", p.get("brand")) == "Assaf"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product.get("product_id"), expected["product_id"])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), expected["source"])
                self.assertEqual(product.get("source_product_url"), expected["source"])
                self.assertEqual(product.get("source_evidence_url"), expected["source"])
                self.assertEqual(product.get("gender"), expected["gender"])
                self.assertEqual(product.get("formats_ml"), sorted(expected["variants"]))

    def test_official_size_variants_are_unique_and_evidence_backed(self):
        for name, expected in EXPECTED.items():
            product = next(
                p for p in self.products
                if p.get("brand_name", p.get("brand")) == "Assaf"
                and p.get("canonical_name") == name
            )
            rows = [v for v in self.variants if v.get("product_id") == product["product_id"]]
            self.assertEqual(sorted(v["size_ml"] for v in rows), sorted(expected["variants"]))
            for variant in rows:
                size = variant["size_ml"]
                with self.subTest(product=name, size=size):
                    source = expected["variants"][size]
                    self.assertEqual(variant.get("source_url"), source)
                    self.assertEqual(variant.get("source_evidence_url"), source)
                    self.assertEqual(variant.get("product_id"), product["product_id"])
                    self.assertNotIn("concentration", variant)
                    self.assertNotIn("gtin", variant)

    def test_family_registry_formats_match_product_catalog(self):
        for name, expected in EXPECTED.items():
            product = next(
                p for p in self.products
                if p.get("brand_name", p.get("brand")) == "Assaf"
                and p.get("canonical_name") == name
            )
            family = self.families[product["family_id"]]
            rows = [r for r in family["products"] if r.get("canonical_name") == name]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("formats_ml"), sorted(expected["variants"]))

    def test_canonical_variant_and_gtin_uniqueness_and_parent_integrity(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        known = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))

    def test_no_retail_offer_data_is_added_to_canonical_records(self):
        forbidden = {
            "price", "currency", "availability", "stock", "shipping_cost",
            "retailer", "offer_url", "store_url",
        }
        selected_ids = {
            p["product_id"] for p in self.products
            if p.get("brand_name", p.get("brand")) == "Assaf"
            and p.get("canonical_name") in EXPECTED
        }
        for variant in self.variants:
            if variant.get("product_id") in selected_ids:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()

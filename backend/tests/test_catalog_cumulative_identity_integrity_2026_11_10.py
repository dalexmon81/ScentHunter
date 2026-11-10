"""Cross-file cumulative catalog identity and family integrity checks."""
import json
import re
import unicodedata
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalized_name(value):
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class CumulativeCatalogIdentityIntegrityTests(unittest.TestCase):
    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_variants_have_existing_product_owner_and_unique_identity(self):
        products = {p["product_id"] for p in CATALOG["products"]}
        variants = CATALOG["variants"]
        self.assertTrue(all(v["product_id"] in products for v in variants))
        keys = [(v["product_id"], v.get("size_ml"), v.get("concentration")) for v in variants]
        self.assertEqual(len(keys), len(set(keys)))

    def test_gtins_are_unique_when_present(self):
        gtins = [v["gtin"] for v in CATALOG["variants"] if v.get("gtin")]
        self.assertEqual(len(gtins), len(set(gtins)))

    def test_no_commercial_offer_data_is_embedded_in_canonical_variants(self):
        forbidden = {
            "price", "price_amount", "currency", "availability", "stock",
            "in_stock", "retailer", "store", "store_id", "offer_url", "shipping_cost"
        }
        for variant in CATALOG["variants"]:
            self.assertFalse(forbidden.intersection(variant), variant.get("variant_id"))

    def test_family_registry_has_no_normalized_duplicate_names(self):
        for family in REGISTRY["families"]:
            keys = [normalized_name(p.get("canonical_name")) for p in family.get("products", [])]
            with self.subTest(family=family.get("family_id")):
                self.assertEqual(len(keys), len(set(keys)))

    def test_catalog_products_map_to_one_registry_row_when_family_exists(self):
        families = {f["family_id"]: f for f in REGISTRY["families"]}
        for product in CATALOG["products"]:
            family = families.get(product.get("family_id"))
            if family is None:
                continue
            key = normalized_name(product.get("canonical_name"))
            matches = [p for p in family.get("products", []) if normalized_name(p.get("canonical_name")) == key]
            with self.subTest(product_id=product.get("product_id")):
                self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main()

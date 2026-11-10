"""Verify Maison Asrar canonical identities against official product-detail pages.

The brand pages confirm the four names below. Size, concentration and GTIN
are intentionally not inferred where the public product page does not expose
those attributes in the catalogue evidence.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Coffee Blend": (
        "SH-MAISON-ASRAR-f401d76f",
        "https://maisonasrar.com/products/coffee-blend-eau-de-parfum",
    ),
    "Soirée": (
        "SH-MAISON-ASRAR-2239c2e7",
        "https://maisonasrar.com/products/soiree",
    ),
    "Vision": (
        "SH-MAISON-ASRAR-d055c340",
        "https://maisonasrar.com/products/vision",
    ),
    "Tornado": (
        "SH-MAISON-ASRAR-e9bedea5",
        "https://maisonasrar.com/products/tornado",
    ),
}


class MaisonAsrarOfficialIdentityPageTests(unittest.TestCase):
    def test_existing_canonical_ids_are_verified_by_individual_brand_pages(self):
        for name, (product_id, url) in EXPECTED.items():
            with self.subTest(product=name):
                records = [
                    p for p in CATALOG["products"]
                    if p.get("brand", p.get("brand_name")) == "Maison Asrar"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(records), 1)
                product = records[0]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_family_registry_identity_is_already_aligned(self):
        family_by_id = {f["family_id"]: f for f in REGISTRY["families"]}
        for name, (product_id, _url) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p["product_id"] == product_id)
                family = family_by_id[product["family_id"]]
                matching = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(matching), 1)

    def test_no_variant_details_are_invented_from_name_only_evidence(self):
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        for name, (product_id, _url) in EXPECTED.items():
            with self.subTest(product=name):
                # These four individual pages currently confirm identity, but
                # the catalogue evidence does not support a size-specific SKU.
                self.assertIn(product_id, product_ids)
                variants = [
                    v for v in CATALOG["variants"]
                    if v.get("product_id") == product_id
                ]
                self.assertEqual(variants, [])


if __name__ == "__main__":
    unittest.main()

"""Official Maison Asrar product-page name audit with evidence-safe attribute limits."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Lumiere": "https://maisonasrar.com/products/lumiere",
    "Night in Paris": "https://maisonasrar.com/products/night-in-paris-maison-asrar-eau-de-perfum-90ml",
    "Patchouli with Love": "https://maisonasrar.com/products/patchouli-with-love-maison-asrar-eau-de-perfum-100-ml",
    "Pink Crush": "https://maisonasrar.com/products/maison-asrar-pink-crush-eau-de-parfum-100-ml-for-women",
    "Qamar": "https://maisonasrar.com/products/qamar",
    "Red Velvet": "https://maisonasrar.com/products/maison-asrar-red-velvet-eau-de-parfum-100-ml-for-women",
    "Rey": "https://maisonasrar.com/collections/new-arrival/products/rey-eau-de-parfum-100ml-maison-asrar",
}


class MaisonAsrarOfficialNameAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(
            family for family in REGISTRY["families"]
            if family.get("family_id") == "maison_asrar_catalog"
        )

    def test_existing_canonical_identities_have_individual_official_page_provenance(self):
        for name, url in EXPECTED.items():
            with self.subTest(product=name):
                rows = [
                    product for product in self.products
                    if product.get("brand") == "Maison Asrar"
                    and product.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(
                    len([v for v in self.variants if v.get("product_id") == product["product_id"]]),
                    0,
                )

    def test_only_explicitly_stated_concentration_is_recorded(self):
        patchouli = next(
            product for product in self.products
            if product.get("brand") == "Maison Asrar"
            and product.get("canonical_name") == "Patchouli with Love"
        )
        self.assertEqual(patchouli.get("concentration"), "Eau de Parfum")
        for name in EXPECTED:
            if name == "Patchouli with Love":
                continue
            product = next(
                product for product in self.products
                if product.get("brand") == "Maison Asrar"
                and product.get("canonical_name") == name
            )
            self.assertNotIn("concentration", product)
            self.assertNotIn("formats_ml", product)
            self.assertNotIn("gtins", product)

    def test_family_registry_keeps_existing_identities_without_invented_formats(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                rows = [
                    item for item in self.family["products"]
                    if item.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                self.assertNotIn("formats_ml", rows[0])

    def test_global_product_variant_and_gtin_integrity_is_preserved(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(v.get("product_id") in known_products for v in self.variants))
        offer_fields = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        for variant in self.variants:
            self.assertTrue(offer_fields.isdisjoint(variant))


if __name__ == "__main__":
    unittest.main()

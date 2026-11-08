"""Regression coverage for Velixir official product pages and size variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PRODUCT_SLUGS = {
    "Adonis": "adonis",
    "Aphrodite": "velixir-aphrodite-eau-de-parfum-for-unisex",
    "Apollo": "apollo",
    "Ares": "ares",
    "Artemis": "velixir-artemis-for-unisex-eau-de-parfum",
    "Asteria": "velixir-asteria-for-unisex-eau-de-parfum",
    "Athena": "athena",
    "Comus": "velixir-parfums-comus-extrait-de-parfum-for-unisex",
    "Concordia": "velixir-concordia-for-unisex-eau-de-parfum",
    "Demeter": "demeter-for-unisex-edp-100ml",
    "Ether": "velixir-parfums-ether-extrait-de-parfum-for-unisex",
    "Galatea": "velixir-galatea-eau-de-parfum-for-unisex",
    "Harmonia": "velixir-parfums-harmonia",
    "Helios": "helios",
    "Hera": "hera",
    "Himeros": "velixir-himeros-for-unisex-eau-de-parfum",
    "Icarus": "icarus",
    "Morpheus": "velixir-morpheus-for-unisex-eau-de-parfum",
    "Narcisus": "narcisus",
    "Nyx": "velixir-parfums-nyx-eau-de-parfum-for-unisex",
    "Orion": "orion",
    "Orpheus": "velixir-parfums-orpheus-extrait-de-parfum-for-unisex",
    "Paladin": "paladin",
    "Panacea": "velixir-parfums-panacea-extrait-de-parfum-for-unisex",
    "Persephone": "velixir-persephone-for-unisex-eau-de-parfum",
    "Poseidon": "velixir-poseidon-for-unisex-eau-de-parfum",
    "Selene": "velixir-parfums-selene-eau-de-parfum-for-unisex",
    "Uranus": "velixir-uranus-for-unisex-eau-de-parfum",
}
EXTRAITS = {"Comus", "Ether", "Orpheus", "Panacea"}


class VelixirOfficialProductVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Velixir"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "velixir_catalog"
        )

    def test_all_catalog_identities_have_individual_official_pages(self):
        self.assertEqual(set(self.products), set(PRODUCT_SLUGS))
        for name, slug in PRODUCT_SLUGS.items():
            url = f"https://velixirparfums.com/products/{slug}"
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)

    def test_edp_products_have_both_explicit_official_sizes(self):
        for name in set(PRODUCT_SLUGS) - EXTRAITS:
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["concentration"], "Eau de Parfum")
                self.assertEqual(product["formats_ml"], [35, 100])
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual({v["size_ml"] for v in matches}, {35, 100})
                self.assertTrue(all(v["concentration"] == "Eau de Parfum" for v in matches))

    def test_extrait_pages_do_not_invent_bottle_sizes(self):
        for name in EXTRAITS:
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["concentration"], "Extrait de Parfum")
                self.assertNotIn("formats_ml", product)
                self.assertFalse(
                    any(v.get("product_id") == product["product_id"] for v in self.variants)
                )

    def test_family_registry_formats_match_edp_variants(self):
        family_products = {
            p["canonical_name"]: p for p in self.family["products"]
        }
        for name in set(PRODUCT_SLUGS) - EXTRAITS:
            with self.subTest(product=name):
                self.assertEqual(family_products[name]["formats_ml"], [35, 100])
        for name in EXTRAITS:
            with self.subTest(product=name):
                self.assertNotIn("formats_ml", family_products[name])

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()

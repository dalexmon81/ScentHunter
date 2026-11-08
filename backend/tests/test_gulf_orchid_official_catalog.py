"""Regression tests for the Gulf Orchid official fragrance catalog reconciliation."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
FAMILY_REGISTRY = json.loads(
    (BACKEND / "family_registry.json").read_text(encoding="utf-8")
)

EXPECTED = {
    "Candy Bite": (
        "https://shop-gulforchid.com/products/candy-bite", 100
    ),
    "Maestro": (
        "https://shop-gulforchid.com/products/maestro", 100
    ),
    "Rice Milk": (
        "https://shop-gulforchid.com/products/rice-milk", 100
    ),
    "Baklava Bite": (
        "https://shop-gulforchid.com/products/baklava-bite", 100
    ),
    "Vanilla Addiction": (
        "https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum", 100
    ),
    "Mango Ice": (
        "https://shop-gulforchid.com/products/mango_ice_eau_de_parfum", 100
    ),
    "Pink Marshmallow": (
        "https://shop-gulforchid.com/products/pink-marshmallow", 100
    ),
    "Coco Blanco": (
        "https://shop-gulforchid.com/products/coco-blanco", 100
    ),
    "Exotic Oud": (
        "https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum", 100
    ),
    "Vanilla Latte": (
        "https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum", 100
    ),
    "Cookie Bite": (
        "https://shop-gulforchid.com/products/cookie-bite", 100
    ),
    "Piña Colada Musk": (
        "https://shop-gulforchid.com/products/gulf-orchid-musk-eau-de-parfum-60-ml", 60
    ),
    "Almalek": (
        "https://shop-gulforchid.com/products/almalek-by-gulf-orchid-eau-de-parfum", 100
    ),
    "Ahlam": (
        "https://shop-gulforchid.com/products/ahlam-by-gulf-orchid-eau-de-parfum", 110
    ),
    "Fresh Oud": (
        "https://shop-gulforchid.com/products/fresh-oud-gulf-orchid-eau-de-parfum-100-ml", 110
    ),
    "Huyam": (
        "https://shop-gulforchid.com/products/huyam_eau_de_parfum", 100
    ),
    "Awham": (
        "https://shop-gulforchid.com/products/awham_eau_de_parfum", 100
    ),
}


class GulfOrchidOfficialCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG.get("products", [])
        cls.variants = CATALOG.get("variants", [])
        cls.gulf_products = {
            row.get("canonical_name"): row
            for row in cls.products
            if row.get("brand_name") == "Gulf Orchid"
        }
        cls.family = next(
            (
                row for row in FAMILY_REGISTRY.get("families", [])
                if row.get("family_id") == "gulf_orchid_catalog"
            ),
            None,
        )

    def test_official_gulf_orchid_fragrances_have_product_and_variant_evidence(self):
        for name, (source_url, size_ml) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.gulf_products.get(name)
                self.assertIsNotNone(product, "missing canonical Gulf Orchid identity")
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertEqual(product.get("source_evidence_url"), source_url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(size_ml, product.get("formats_ml", []))
                matching = [
                    row for row in self.variants
                    if row.get("product_id") == product.get("product_id")
                    and row.get("size_ml") == size_ml
                    and row.get("concentration") == "Eau de Parfum"
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("source_evidence_url"), source_url)

    def test_vanilla_aura_and_vanilla_voyage_are_attributed_to_maison_asrar(self):
        for name in ("Vanilla Aura", "Vanilla Voyage"):
            with self.subTest(product=name):
                self.assertNotIn(name, self.gulf_products)
                maison = [
                    row for row in self.products
                    if row.get("brand_name") == "Maison Asrar"
                    and row.get("canonical_name") == name
                ]
                self.assertEqual(len(maison), 1)

    def test_baklava_bite_is_a_single_perfume_not_the_bite_menu_bundle(self):
        product = self.gulf_products.get("Baklava Bite")
        self.assertIsNotNone(product)
        self.assertEqual(
            product.get("source_url"),
            "https://shop-gulforchid.com/products/baklava-bite",
        )
        self.assertFalse(
            any(
                "bite menu" in str(row.get("canonical_name") or "").casefold()
                or "bite collection" in str(row.get("canonical_name") or "").casefold()
                for row in self.gulf_products.values()
            )
        )

    def test_family_registry_and_catalog_have_the_same_gulf_orchid_identities(self):
        self.assertIsNotNone(self.family)
        family_names = {
            row.get("canonical_name")
            for row in self.family.get("products", [])
        }
        self.assertEqual(family_names, set(self.gulf_products))

    def test_gulf_orchid_variant_ids_and_parent_links_are_valid(self):
        product_ids = {row.get("product_id") for row in self.gulf_products.values()}
        variant_ids = [
            row.get("variant_id") for row in self.variants
            if row.get("product_id") in product_ids
        ]
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        for variant in self.variants:
            if variant.get("product_id") in product_ids:
                self.assertIsInstance(variant.get("size_ml"), int)
                self.assertGreater(variant["size_ml"], 0)


if __name__ == "__main__":
    unittest.main()

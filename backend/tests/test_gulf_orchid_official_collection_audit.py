"""Regression guard for the paginated Gulf Orchid official perfume collection."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
COLLECTION_PAGE_1 = "https://shop-gulforchid.com/collections/gulf-orchid-perfume"
COLLECTION_PAGE_2 = COLLECTION_PAGE_1 + "?page=2"

EXPECTED_URLS = {
    "Vanilla Addiction": "https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum",
    "Mango Ice": "https://shop-gulforchid.com/products/mango_ice_eau_de_parfum",
    "Cotton Candy Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-cotton-candy",
    "Tahara Vanilla Musk": "https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml",
    "Sweet Heaven": "https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml",
    "Pink Marshmallow": "https://shop-gulforchid.com/products/pink-marshmallow",
    "Coco Blanco": "https://shop-gulforchid.com/products/coco-blanco",
    "Exotic Oud": "https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum",
    "Vanilla Latte": "https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum",
    "Cookie Bite": "https://shop-gulforchid.com/products/cookie-bite",
    "Sweet Like Candy": "https://shop-gulforchid.com/products/sweet_like_candy_eau_de_parfum",
    "Sweet Heaven Extreme": "https://shop-gulforchid.com/products/sweet-heaven-extreme-by-gulf-orchid-eau-de-parfum-20ml",
    "Piña Colada Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-pina-colada",
    "Angel Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-angel",
    "Naughty Vanilla": "https://shop-gulforchid.com/products/naughty-vanilla",
    "Yacht Club": "https://shop-gulforchid.com/products/yacht_club_eau_de_parfum",
    "Sweet Heaven Cherry": "https://shop-gulforchid.com/products/sweet_heaven_cherry_20_ml_eau_de_parfum",
    "Candy Bite": "https://shop-gulforchid.com/products/candy-bite",
    "Sweet Cherry Kiss": "https://shop-gulforchid.com/products/sweet_cherry_kiss_eau_de_parfum",
    "Creamy Pistachio": "https://shop-gulforchid.com/products/creamy_pistachio_eau_de_parfum",
    "Marshmallow": "https://shop-gulforchid.com/products/marshmallow",
    "Sweet Heaven Ice": "https://shop-gulforchid.com/products/sweet_heaven_ice_eau_de_parfum",
    "Crème Caramel": "https://shop-gulforchid.com/products/creme_caramel_eau_de_parfum",
    "Pomegranate Musk": "https://shop-gulforchid.com/products/pomegranate-musk-eau-de-parfum-60ml",
    "Mysterious Tahara Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-mysterious-tahara",
    "Toffee Musk": "https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-toffee",
}
EXPECTED_VARIANTS = {
    "Vanilla Addiction": [100], "Mango Ice": [100],
    "Sweet Heaven": [20, 100], "Pink Marshmallow": [100],
    "Coco Blanco": [100], "Exotic Oud": [100], "Vanilla Latte": [100],
    "Cookie Bite": [100], "Sweet Like Candy": [100],
    "Sweet Heaven Extreme": [20, 100], "Piña Colada Musk": [60],
    "Angel Musk": [60], "Naughty Vanilla": [100], "Yacht Club": [100],
    "Sweet Heaven Cherry": [20], "Candy Bite": [100], "Sweet Cherry Kiss": [100],
    "Creamy Pistachio": [100], "Marshmallow": [100], "Sweet Heaven Ice": [100],
    "Crème Caramel": [100], "Pomegranate Musk": [60],
    "Mysterious Tahara Musk": [60], "Toffee Musk": [60],
}
COLLECTION_ONLY_LABELS = ("Al Qasr", "Asala", "Hamsat", "Hikma", "Jawhara", "Jewel", "Riwaya", "Turath")
BUNDLES = ("Sweet Edition", "Flirt Edition")


class GulfOrchidOfficialCollectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (BACKEND / "product_catalog.json").open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [p for p in cls.catalog["products"] if p.get("brand") == "Gulf Orchid"]
        cls.by_name = {p.get("canonical_name"): p for p in cls.products}
        cls.variants = cls.catalog["variants"]

    def test_both_paginated_collection_pages_are_represented(self):
        self.assertEqual(set(self.by_name), set(EXPECTED_URLS))
        self.assertEqual(len(self.products), 26)

    def test_all_canonical_names_have_official_product_page_provenance(self):
        for name, url in EXPECTED_URLS.items():
            with self.subTest(name=name):
                row = self.by_name[name]
                self.assertEqual(row.get("source_url"), url)
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("concentration"), "Eau de Parfum")

    def test_only_explicitly_documented_sizes_become_variants(self):
        for name, sizes in EXPECTED_VARIANTS.items():
            with self.subTest(name=name):
                row = self.by_name[name]
                self.assertEqual(row.get("formats_ml"), sizes)
                actual = sorted(v["size_ml"] for v in self.variants if v.get("product_id") == row["product_id"])
                self.assertEqual(actual, sorted(sizes))
                for variant in (v for v in self.variants if v.get("product_id") == row["product_id"]):
                    self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                    self.assertTrue(variant.get("source_evidence_url"))

    def test_products_without_verified_size_have_no_invented_variants(self):
        for name in ("Cotton Candy Musk", "Tahara Vanilla Musk"):
            with self.subTest(name=name):
                row = self.by_name[name]
                self.assertNotIn("formats_ml", row)
                self.assertFalse(any(v.get("product_id") == row["product_id"] for v in self.variants))

    def test_collection_labels_and_gift_bundles_are_not_canonical_perfumes(self):
        names = set(self.by_name)
        for name in COLLECTION_ONLY_LABELS + BUNDLES:
            with self.subTest(name=name):
                self.assertNotIn(name, names)

    def test_vanilla_aura_and_vanilla_voyage_are_not_misattributed_to_gulf_orchid(self):
        names = set(self.by_name)
        self.assertNotIn("Vanilla Aura", names)
        self.assertNotIn("Vanilla Voyage", names)

    def test_family_registry_matches_the_audited_gulf_orchid_product_set(self):
        with (BACKEND / "family_registry.json").open(encoding="utf-8") as handle:
            registry = json.load(handle)
        family = next(row for row in registry["families"] if row.get("family_id") == "gulf_orchid_catalog")
        names = {row.get("canonical_name") for row in family["products"]}
        self.assertEqual(names, set(EXPECTED_URLS))

    def test_no_duplicate_gulf_orchid_product_names(self):
        names = [p.get("canonical_name", "").casefold() for p in self.products]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()

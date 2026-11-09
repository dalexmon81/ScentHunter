"""Regression tests for official Al Haramain and Gulf Orchid name harvest."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
AL_HARAMAIN = ["Haramain Musk Orchid","Haramain Xplore Sapphire","Azlan Oud Bleu Edition","Amber Oud Ultra Violet","Azlan Oud Saffron Edition","Amber Oud Tobacco Edition","L'Aventure Grapefruit","L'Aventure Fraiche","L'Aventure Ciel","Azlan Oud Amber Edition","Portfolio Cupid's Rose","Portfolio Portrait Sandal","Portfolio Oriental Forest","Mystique Musk Spray","Amber Oud Gold Edition","Portfolio Euphoric Roots","Azlan Oud Charcoal Edition","Detour Noir Exclusif","Junoon Noir","Oud Cambodi","Maryam","Urbanist Femme","Mystique Femme","Mystique Homme","Detour Nasr","Musk","Detour Noir Intense","L'Aventure Rose","L'Aventure Blanche","Solitaire Musk","Musk Collection","Rawaa","Night Dreams","Khulasat Al Oud","Fall In Love Orange","Fall In Love Pink","Junoon Rose","Maze","Opposite Pink","Manege Blanche","Rafia Gold","Amber Musk","Opulent Sapphire","Royal Musk","Etoiles Silver","Madinah","Portfolio Floral Sculpture","Manege Rouge","Jameela","Musk Maliki","Oyuny","Chateau De La Haramain Argent","Das Ziel","Mystique","Treasure","Oudh Patchouli","Farasha","Asrar Khafiya","Urbanist Prive Silver","Mena","Areej Al Oud"]
GULF_ORCHID = ["Sweet Like Candy","Sweet Heaven Extreme 20ML","Piña Colada Musk","Al Qasr","Hikma","Riwaya"]
GULF_ORCHID_DETAIL_VERIFIED = {
    "Vanilla Addiction": ("https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum", 100, "Eau de Parfum"),
    "Mango Ice": ("https://shop-gulforchid.com/products/mango_ice_eau_de_parfum", 100, "Eau de Parfum"),
    "Cotton Candy Musk": ("https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-cotton-candy", None, None),
    "Tahara Vanilla Musk": ("https://shop-gulforchid.com/products/musk-eau-de-parfum-60-ml", None, None),
    "Sweet Heaven 20ML": ("https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml", 20, "Eau de Parfum"),
    "Pink Marshmallow": ("https://shop-gulforchid.com/products/pink-marshmallow", 100, "Eau de Parfum"),
    "Coco Blanco": ("https://shop-gulforchid.com/products/coco-blanco", 100, "Eau de Parfum"),
    "Exotic Oud": ("https://shop-gulforchid.com/products/exotic_oud_eau_de_parfum", 100, "Eau de Parfum"),
    "Vanilla Latte": ("https://shop-gulforchid.com/products/vanilla_latte_eau_de_parfum", 100, "Eau de Parfum"),
    "Cookie Bite": ("https://shop-gulforchid.com/products/cookie-bite", 100, "Eau de Parfum"),
    "Sweet Like Candy": ("https://shop-gulforchid.com/products/sweet_like_candy_eau_de_parfum", 100, "Eau de Parfum"),
    "Sweet Heaven Extreme 20ML": ("https://shop-gulforchid.com/products/sweet-heaven-extreme-by-gulf-orchid-eau-de-parfum-20ml", 20, "Eau de Parfum"),
    "Piña Colada Musk": ("https://shop-gulforchid.com/products/gulf-orchid-musk-tahara-eau-de-parfum-pina-colada", 60, "Eau de Parfum"),
}

MAISON_ASRAR_REATTRIBUTED = {
    "Asala": ("https://shop-gulforchid.com/collections/asala-collection", "source_listed_name", None),
    "Turath": ("https://shop-gulforchid.com/products/turath-eau-de-perfum-100ml", "source_verified_name", (100, "Eau de Parfum")),
    "Vanilla Aura": ("https://maisonasrar.com/products/vanilla-aura", "source_verified_name", (100, "Eau de Parfum")),
    "Vanilla Voyage": ("https://shop-gulforchid.com/products/maison-asrar-vanilla-voyage-eau-de-parfum", "source_verified_name", None),
}

class OfficialStoreRangeHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]

    @staticmethod
    def _normalize(name):
        value = unicodedata.normalize("NFKD", name)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    def _brand_names(self, brand):
        return {self._normalize(p["canonical_name"]) for p in self.products if p.get("brand") == brand}

    def test_all_al_haramain_store_names_present(self):
        names = self._brand_names("Al Haramain")
        for name in AL_HARAMAIN:
            with self.subTest(name=name):
                self.assertIn(self._normalize(name), names)

    def test_all_gulf_orchid_store_names_present(self):
        names = self._brand_names("Gulf Orchid")
        for name in GULF_ORCHID:
            with self.subTest(name=name):
                self.assertIn(self._normalize(name), names)

    def test_no_duplicate_brand_name_pairs(self):
        pairs = [(p.get("brand"), p["canonical_name"].casefold()) for p in self.products]
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_harvest_rows_have_no_invented_variants(self):
        for product in self.products:
            if product["product_id"].startswith(("SH-AL-HARAMAIN-STORE-", "SH-GULF-ORCHID-STORE-")):
                if product.get("brand") == "Gulf Orchid" and product.get("canonical_name") in GULF_ORCHID_DETAIL_VERIFIED:
                    continue
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)


    def test_gulf_orchid_official_product_pages_have_verified_identity_provenance(self):
        products_by_name = {
            row.get("canonical_name"): row
            for row in self.products
            if row.get("brand") == "Gulf Orchid"
        }
        for name, (source_url, size_ml, concentration) in GULF_ORCHID_DETAIL_VERIFIED.items():
            with self.subTest(name=name):
                self.assertIn(name, products_by_name)
                rows = [
                    row for row in self.products
                    if row.get("brand") == "Gulf Orchid"
                    and row.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                variants = [
                    variant for variant in self.catalog.get("variants", [])
                    if variant.get("product_id") == row["product_id"]
                ]
                if size_ml is None:
                    # The official detail page proves the identity, but the
                    # inspected page content does not expose size/concentration.
                    self.assertNotIn("concentration", row)
                    self.assertNotIn("formats_ml", row)
                    self.assertEqual(variants, [])
                else:
                    self.assertEqual(row.get("concentration"), concentration)
                    self.assertEqual(row.get("formats_ml"), [size_ml])
                    self.assertEqual(len(variants), 1)
                    self.assertEqual(variants[0].get("size_ml"), size_ml)
                    self.assertEqual(variants[0].get("concentration"), concentration)
                    expected_variant_source = (
                        "https://shop-gulforchid.com/products/vanilla-aura"
                        if name == "Vanilla Aura" else source_url
                    )
                    self.assertEqual(variants[0].get("source_evidence_url"), expected_variant_source)

    def test_gulf_orchid_detail_harvest_does_not_duplicate_variant_ids(self):
        variant_ids = [variant["variant_id"] for variant in self.catalog.get("variants", [])]
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


    def test_gulf_orchid_legacy_detail_pages_and_sizes_are_verified(self):
        expected = {
            "Al Qasr": ("https://shop-gulforchid.com/products/al-qasr-silver", 100, "Eau de Parfum"),
            "Hikma": ("https://shop-gulforchid.com/products/hikma-by-gulf-orchid-eau-de-parfum", 110, "Eau de Parfum"),
            "Riwaya": ("https://shop-gulforchid.com/products/riwaya_eau_de_parfum", 100, "Eau de Parfum"),
        }
        for name, (source_url, size_ml, concentration) in expected.items():
            with self.subTest(name=name):
                rows = [
                    row for row in self.products
                    if row.get("brand") == "Gulf Orchid"
                    and row.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), source_url)
                self.assertEqual(row.get("concentration"), concentration)
                self.assertEqual(row.get("formats_ml"), [size_ml])
                variants = [
                    variant for variant in self.catalog.get("variants", [])
                    if variant.get("product_id") == row["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), size_ml)
                self.assertEqual(variants[0].get("concentration"), concentration)
                self.assertEqual(variants[0].get("source_evidence_url"), source_url)

    def test_store_collection_brand_filters_correct_maison_asrar_attribution(self):
        for name, (source_url, status, size_spec) in MAISON_ASRAR_REATTRIBUTED.items():
            with self.subTest(name=name):
                rows = [
                    row for row in self.products
                    if row.get("canonical_name") == name
                    and row.get("brand") == "Maison Asrar"
                ]
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertEqual(row.get("identity_status"), status)
                self.assertEqual(row.get("source_url"), source_url)
                variants = [
                    variant for variant in self.catalog.get("variants", [])
                    if variant.get("product_id") == row["product_id"]
                ]
                if size_spec is None:
                    self.assertNotIn("concentration", row)
                    self.assertNotIn("formats_ml", row)
                    self.assertEqual(variants, [])
                else:
                    size_ml, concentration = size_spec
                    self.assertEqual(row.get("concentration"), concentration)
                    self.assertEqual(row.get("formats_ml"), [size_ml])
                    self.assertEqual(len(variants), 1)
                    self.assertEqual(variants[0].get("size_ml"), size_ml)
                    self.assertEqual(variants[0].get("concentration"), concentration)
                    self.assertEqual(variants[0].get("source_evidence_url"), source_url)


    def test_maison_asrar_collection_labels_are_not_canonical_perfume_identities(self):
        # These are collection names, not standalone perfumes. The actual
        # products displayed within those collections already have identities.
        for name in ("Hamsat", "Jawhara", "Jewel"):
            with self.subTest(collection=name):
                self.assertFalse(any(
                    row.get("canonical_name") == name
                    for row in self.products
                ))
        expected_products = (
            "Hamsat Gharam", "Hamsat Hob", "Hamsat Ghazal", "Hamsat Ishq",
            "Jawhara Rouge", "Jawhara Black",
            "Date Night", "Red Velvet", "Pink Crush",
        )
        maison_names = self._brand_names("Maison Asrar")
        for name in expected_products:
            with self.subTest(product=name):
                self.assertIn(self._normalize(name), maison_names)

if __name__ == "__main__":
    unittest.main()

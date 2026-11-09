"""Regression tests for official Al Haramain and Gulf Orchid name harvest."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
AL_HARAMAIN = ["Haramain Musk Orchid","Haramain Xplore Sapphire","Azlan Oud Bleu Edition","Amber Oud Ultra Violet","Azlan Oud Saffron Edition","Amber Oud Tobacco Edition","L'Aventure Grapefruit","L'Aventure Fraiche","L'Aventure Ciel","Azlan Oud Amber Edition","Portfolio Cupid's Rose","Portfolio Portrait Sandal","Portfolio Oriental Forest","Mystique Musk Spray","Amber Oud Gold Edition","Portfolio Euphoric Roots","Azlan Oud Charcoal Edition","Detour Noir Exclusif","Junoon Noir","Oud Cambodi","Maryam","Urbanist Femme","Mystique Femme","Mystique Homme","Detour Nasr","Musk","Detour Noir Intense","L'Aventure Rose","L'Aventure Blanche","Solitaire Musk","Musk Collection","Rawaa","Night Dreams","Khulasat Al Oud","Fall In Love Orange","Fall In Love Pink","Junoon Rose","Maze","Opposite Pink","Manege Blanche","Rafia Gold","Amber Musk","Opulent Sapphire","Royal Musk","Etoiles Silver","Madinah","Portfolio Floral Sculpture","Manege Rouge","Jameela","Musk Maliki","Oyuny","Chateau De La Haramain Argent","Das Ziel","Mystique","Treasure","Oudh Patchouli","Farasha","Asrar Khafiya","Urbanist Prive Silver","Mena","Areej Al Oud"]
GULF_ORCHID = ["Sweet Like Candy","Sweet Heaven Extreme 20ML","Piña Colada Musk"]

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
                if product["identity_status"] == "source_verified_name":
                    source = product.get("source_url", "")
                    self.assertTrue("/products/" in source or source.endswith(".html"))
                    continue
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)

    def test_gulf_orchid_individual_official_pages_and_explicit_variants(self):
        expected = {
            "Vanilla Addiction": ("https://shop-gulforchid.com/products/vanilla_addiction_eau_de_parfum", 100),
            "Mango Ice": ("https://shop-gulforchid.com/products/mango_ice_eau_de_parfum", 100),
            "Sweet Heaven 20ML": ("https://shop-gulforchid.com/products/sweet-heaven-by-gulf-orchid-eau-de-parfum-20ml", 20),
            "Pink Marshmallow": ("https://shop-gulforchid.com/products/pink-marshmallow", 100),
            "Coco Blanco": ("https://shop-gulforchid.com/products/coco-blanco", 100),
            "Belle": ("https://shop-gulforchid.com/products/belle", 100),
            "Amour": ("https://shop-gulforchid.com/products/amour", 100),
            "Chic": ("https://shop-gulforchid.com/products/chic", 100),
            "Cloud 9": ("https://shop-gulforchid.com/products/cloud-9", 100),
            "Phantom": ("https://shop-gulforchid.com/products/phantom", 100),
            "Flamma": ("https://shop-gulforchid.com/products/flamma", 100),
            "Vortex": ("https://shop-gulforchid.com/products/vortex", 100),
            "Rosalia": ("https://shop-gulforchid.com/products/rosalia", 100),
            "Maestro": ("https://shop-gulforchid.com/products/maestro", 100),
        }
        products = {
            p["canonical_name"]: p for p in self.products
            if p.get("brand_name") == "Gulf Orchid"
        }
        variants = self.catalog.get("variants", [])
        for name, (source_url, size_ml) in expected.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(size_ml, product.get("formats_ml", []))
                matches = [
                    v for v in variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matches[0].get("source_evidence_url"), source_url)

    def test_gulf_orchid_new_arrivals_are_unique_canonical_identities(self):
        expected = {"Belle", "Amour", "Chic", "Cloud 9", "Phantom", "Flamma", "Vortex", "Rosalia", "Maestro"}
        rows = [
            p for p in self.products
            if p.get("brand_name") == "Gulf Orchid" and p.get("canonical_name") in expected
        ]
        self.assertEqual({p["canonical_name"] for p in rows}, expected)
        self.assertEqual(len(rows), len(expected))
        self.assertEqual(len({p["product_id"] for p in rows}), len(expected))

if __name__ == "__main__":
    unittest.main()

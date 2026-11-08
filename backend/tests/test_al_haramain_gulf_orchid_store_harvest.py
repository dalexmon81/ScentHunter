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
            product_id = product["product_id"]
            if product_id == "SH-GULF-ORCHID-STORE-003":
                # PR #542 replaces the collection-only listing with an
                # individual official 60 ml Eau de Parfum product page.
                self.assertEqual(product["canonical_name"], "Piña Colada Musk")
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(
                    product["source_url"],
                    "https://shop-gulforchid.com/products/gulf-orchid-musk-eau-de-parfum-60-ml",
                )
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [60])
                matching = [
                    row for row in self.catalog["variants"]
                    if row.get("product_id") == product_id and row.get("size_ml") == 60
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(
                    matching[0].get("source_evidence_url"),
                    product["source_url"],
                )
            elif product_id.startswith(("SH-AL-HARAMAIN-STORE-", "SH-GULF-ORCHID-STORE-")):
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)

if __name__ == "__main__":
    unittest.main()

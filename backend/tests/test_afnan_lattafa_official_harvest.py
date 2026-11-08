"""Regression checks for official Afnan and Lattafa Europe collection harvest."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
LATTAFA_NAMES = ["Eclaire","Badee Al Oud Black Exposed","Khamrah Qahwa","His Confession","Her Confession","Pride Eternal Vanille","Badee Al Oud Honor & Glory","Fakhar Men","Badee Al Oud","Yara","The Kingdom Men","Khamrah Dukhan","Atlas","Badee Al Oud Amethyst","Ana Abiyedh","Pride Art of Arabia I","Pride Nebras","Opulent Oud","The Kingdom Women","Pride Vintage Radio","Pride Art Of Universe","Ajwad Pink to Pink Creamy Elixir","Fakhar Women"]

class AfnanLattafaOfficialHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)

    @staticmethod
    def normalize(name):
        value = unicodedata.normalize("NFKD", name)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    def test_official_lattafa_names_present(self):
        names = {self.normalize(p["canonical_name"]) for p in self.catalog["products"] if p.get("brand") == "Lattafa"}
        for name in LATTAFA_NAMES:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), names)

    def test_afnan_tapis_rouge_official_short_name_is_alias(self):
        product = next(p for p in self.catalog["products"] if p.get("brand") == "Afnan" and self.normalize(p["canonical_name"]) == self.normalize("SUPREMACY TAPIS ROUGE - LUXURY COLLECTION"))
        aliases = {self.normalize(alias) for alias in product.get("aliases", [])}
        self.assertIn(self.normalize("Supremacy Tapis Rouge"), aliases)

    def test_no_duplicate_product_ids_or_brand_names(self):
        products = self.catalog["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand"), self.normalize(p["canonical_name"])) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_harvested_rows_have_no_inferred_variant_data(self):
        for product in self.catalog["products"]:
            if product["product_id"].startswith("SH-LATTAFA-EU-HARVEST-"):
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertEqual(product["source_url"], "https://lattafaparfum.eu/de-de/collections/all")
                self.assertNotIn("concentration", product)
                self.assertNotIn("formats_ml", product)

if __name__ == "__main__":
    unittest.main()

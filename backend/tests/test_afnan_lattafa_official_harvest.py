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


    def test_afnan_nine_series_official_detail_pages_and_100ml_variants_are_verified(self):
        expected = {
            "9 PM Night Out": (
                "https://de.afnan.com/en/products/9pm-night-out",
                "https://www.fr.afnan.com/en/products/9pm-night-out",
                "Extrait de Parfum",
            ),
            "9 PM Elixir": (
                "https://www.fr.afnan.com/en/products/9-pm-elixir",
                "https://www.fr.afnan.com/en/products/9-pm-elixir",
                "Extrait de Parfum",
            ),
            "9 PM Pour Femme": (
                "https://www.fr.afnan.com/en/products/9-pm-pour-femme",
                "https://www.fr.afnan.com/en/products/9-pm-pour-femme",
                "Eau de Parfum",
            ),
            "9 AM": (
                "https://www.fr.afnan.com/en/products/9-am",
                "https://www.fr.afnan.com/en/products/9-am",
                "Eau de Parfum",
            ),
            "9 AM Pour Femme": (
                "https://www.fr.afnan.com/en/products/9-am-pour-femme",
                "https://www.fr.afnan.com/en/products/9-am-pour-femme",
                "Eau de Parfum",
            ),
            "9 AM Dive": (
                "https://www.fr.afnan.com/en/products/9-am-dive",
                "https://www.fr.afnan.com/en/products/9-am-dive",
                "Eau de Parfum",
            ),
            "9 PM Rebel": (
                "https://www.fr.afnan.com/en/products/9-pm-rebel",
                "https://www.fr.afnan.com/en/products/9-pm-rebel",
                "Eau de Parfum",
            ),
            "9 PM": (
                "https://www.fr.afnan.com/en/products/9-pm",
                "https://www.fr.afnan.com/en/products/9-pm",
                "Eau de Parfum",
            ),
        }
        for name, (source_url, evidence_url, concentration) in expected.items():
            with self.subTest(name=name):
                product = next(
                    p for p in self.catalog["products"]
                    if p.get("brand") == "Afnan" and p.get("canonical_name") == name
                )
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertEqual(product.get("source_product_url"), source_url)
                self.assertEqual(product.get("source_evidence_url"), evidence_url)
                self.assertEqual(product.get("concentration"), concentration)
                self.assertIn(100, product.get("formats_ml", []))
                variants = [
                    v for v in self.catalog["variants"]
                    if v.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), 100)
                self.assertEqual(variants[0].get("concentration"), concentration)
                self.assertEqual(variants[0].get("source_evidence_url"), evidence_url)

    def test_afnan_extrait_and_edp_are_kept_as_distinct_concentrations(self):
        for name in ("9 PM Night Out", "9 PM Elixir"):
            product = next(
                p for p in self.catalog["products"]
                if p.get("brand") == "Afnan" and p.get("canonical_name") == name
            )
            self.assertEqual(product.get("concentration"), "Extrait de Parfum")
        for name in ("9 PM", "9 PM Pour Femme", "9 AM", "9 AM Pour Femme", "9 AM Dive", "9 PM Rebel"):
            product = next(
                p for p in self.catalog["products"]
                if p.get("brand") == "Afnan" and p.get("canonical_name") == name
            )
            self.assertEqual(product.get("concentration"), "Eau de Parfum")

if __name__ == "__main__":
    unittest.main()

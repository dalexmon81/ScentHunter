"""Regression tests for the Khadlaj official perfume-spray harvest."""
import json
import unittest
import unicodedata
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = ["Oud Pure Oud Barakat","Oud Pure Oud Galazaid","Oud Pure Oud Jumeirah","Hareem Al Sultan","Azure Velvet","Maison L'Imaginaire","Saqr Al Badiya","Opus Reborn","Musk Pour Amber","Fursan Brown","Sara","Musk Pure Musk Blend Creation of Iqbal","Le Prestige King","The Proposal Date Night","Le Prestige Royal","Le Prestige Empress","Le Prestige Bold","The Proposal Special Occasion","25 Experience","25 Trust","25 Loyalty","25 Heritage","25 Integrity","Valor Mystique","Valor Honor","Valor Chivalry","Valor Enigma","Empire Empress","Empire Crown","Empire Regent","Karus Blu Spice","Karus Secret Musk","Karus Oud Fire","Karus Amber Gold","Maison Creation De Reve","Maison Epoque Artistique","Maison L'Or Noir","Maison Flor Oud","Wild Indonesian Oud","Mystical Indian Oud Pure","Oud Pour Noble","Musk Pour Narcis","Oud Pour Shaikh","Oud Pour Rouge","Oud Pour Blueberry","Infini Absolute","Cashmere Warm Oud","Cashmere Sunshine Musk","Oud Noir","Sensuous Night","Ombre Notes","Ghadeer Silver","Musk Al Sabah","Oud Al Sabah","Magnate Noble","Magnate Premier","Infini","Shahi Oud","Barwaaz Solid Grey","Rose Couture","Musk Couture"]

class KhadlajOfficialSprayHarvestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)

    @staticmethod
    def normalize(name):
        value = unicodedata.normalize("NFKD", name)
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        return "".join(ch for ch in value.casefold() if ch.isalnum())

    def test_all_harvested_khadlaj_names_present(self):
        names = {self.normalize(p["canonical_name"]) for p in self.catalog["products"] if p.get("brand") == "Khadlaj"}
        for name in EXPECTED:
            with self.subTest(name=name):
                self.assertIn(self.normalize(name), names)

    def test_no_duplicate_product_ids_or_brand_names(self):
        products = self.catalog["products"]
        ids = [p["product_id"] for p in products]
        pairs = [(p.get("brand"), self.normalize(p["canonical_name"])) for p in products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_harvest_rows_with_first_party_variant_evidence_are_not_name_only(self):
        variants_by_product = {}
        for variant in self.catalog["variants"]:
            variants_by_product.setdefault(variant["product_id"], []).append(variant)

        for product in self.catalog["products"]:
            if not product["product_id"].startswith("SH-KHADLAJ-SPRAY-HARVEST-"):
                continue
            variants = variants_by_product.get(product["product_id"], [])
            formats = product.get("formats_ml", [])
            if formats:
                self.assertTrue(product.get("source_evidence_url", "").startswith("https://khadlaj-perfumes.com/"))
                self.assertEqual(product["identity_status"], "source_listed_name" if product["source_url"] == "https://khadlaj-perfumes.com/collections/perfumes-spray" else "source_verified_name")
                for size in formats:
                    matching = [v for v in variants if v["size_ml"] == size]
                    self.assertEqual(len(matching), 1, product["canonical_name"])
                    if product.get("concentration"):
                        self.assertEqual(matching[0].get("concentration"), product["concentration"])
            else:
                self.assertEqual(product["identity_status"], "source_listed_name")
                self.assertEqual(product["source_url"], "https://khadlaj-perfumes.com/collections/perfumes-spray")
                self.assertNotIn("concentration", product)
                self.assertEqual(variants, [])

    def test_additional_official_detail_variants_are_verified(self):
        expected = {
            "Panache Eleganza": (100, "Extrait de Parfum"),
            "Stellar Musk": (100, "Eau de Parfum"),
            "Stellar Oud": (100, "Eau de Parfum"),
            "Onyx Galaxy": (100, "Eau de Parfum"),
            "Muse": (100, "Eau de Parfum"),
            "Sueno": (100, "Extrait de Parfum"),
            "Saraya": (60, "Extrait de Parfum"),
            "Zayaan Silver": (100, "Eau de Parfum"),
            "Qarar": (60, "Extrait de Parfum"),
        }
        for name, (size, concentration) in expected.items():
            with self.subTest(name=name):
                product = next(
                    p for p in self.catalog["products"]
                    if p.get("brand") == "Khadlaj" and p.get("canonical_name") == name
                )
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertIn(size, product["formats_ml"])
                self.assertEqual(product["concentration"], concentration)
                self.assertTrue(product["source_url"].startswith("https://khadlaj-perfumes.com/"))
                variants = [
                    v for v in self.catalog["variants"]
                    if v["product_id"] == product["product_id"] and v["size_ml"] == size
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["concentration"], concentration)

    def test_sensuos_spelling_is_an_alias_not_a_duplicate(self):
        product = next(
            p for p in self.catalog["products"]
            if p.get("brand") == "Khadlaj" and p.get("canonical_name") == "Sensuous Night"
        )
        self.assertIn("Sensuos Night", product["aliases"])
        self.assertIn("Sensous Night", product["aliases"])

    def test_hareem_al_sultan_and_gold_are_distinct_variants(self):
        regular = next(
            p for p in self.catalog["products"]
            if p.get("brand") == "Khadlaj" and p.get("canonical_name") == "Hareem Al Sultan"
        )
        gold = next(
            p for p in self.catalog["products"]
            if p.get("brand") == "Khadlaj" and p.get("canonical_name") == "Hareem Al Sultan Gold"
        )
        regular_variants = [v for v in self.catalog["variants"] if v["product_id"] == regular["product_id"]]
        gold_variants = [v for v in self.catalog["variants"] if v["product_id"] == gold["product_id"]]
        self.assertEqual([(v["size_ml"], v.get("concentration")) for v in regular_variants], [(75, "Eau de Parfum")])
        self.assertEqual([(v["size_ml"], v.get("concentration")) for v in gold_variants], [(35, gold_variants[0].get("concentration"))])

if __name__ == "__main__":
    unittest.main()

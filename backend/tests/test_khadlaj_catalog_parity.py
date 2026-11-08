"""Regression tests for Khadlaj catalog/family registry coverage."""
import json
import unittest
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalized(value):
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


class KhadlajCatalogParityTests(unittest.TestCase):
    def setUp(self):
        self.products = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"]
        self.families = [f for f in REGISTRY["families"] if f.get("brand") == "Khadlaj"]

    def test_every_catalog_family_has_a_registry_family(self):
        catalog_family_ids = {p["family_id"] for p in self.products}
        registry_family_ids = {f["family_id"] for f in self.families}
        self.assertTrue(catalog_family_ids.issubset(registry_family_ids))

    def test_every_catalog_product_is_covered_by_its_family(self):
        for product in self.products:
            family = next(f for f in self.families if f["family_id"] == product["family_id"])
            names = {normalized(p["canonical_name"]) for p in family["products"]}
            self.assertIn(normalized(product["canonical_name"]), names, product["canonical_name"])

    def test_catalog_product_and_family_names_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        names = [p["canonical_name"].casefold() for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))

    def test_shiyaaka_remains_a_distinct_line(self):
        shiyaaka = next(f for f in self.families if f["family_id"] == "khadlaj_shiyaaka")
        self.assertEqual(len(shiyaaka["products"]), 8)
        self.assertIn("Shiyaaka Blue", {p["canonical_name"] for p in shiyaaka["products"]})

    def test_official_spray_collection_remains_separate(self):
        sprays = next(
            f for f in self.families
            if f["family_id"] == "khadlaj_official_perfume_sprays_2026_11"
        )
        catalog_family_ids = {p["family_id"] for p in self.products}
        self.assertIn(sprays["family_id"], catalog_family_ids)
        self.assertEqual(len([p for p in self.products if p["family_id"] == sprays["family_id"]]), 62)
        self.assertGreater(len(sprays["products"]), 0)

    def test_perfume_oil_identity_is_not_recast_as_a_spray_variant(self):
        maya = next(p for p in self.products if p["canonical_name"] == "Maya")
        self.assertEqual(maya.get("formats_ml"), [20])
        self.assertEqual(maya.get("concentration"), "Perfume Oil")
        self.assertTrue(any(v.get("product_id") == maya["product_id"] and v.get("size_ml") == 20 and v.get("concentration") == "Perfume Oil" for v in CATALOG["variants"]))



    def test_reconciled_khadlaj_totals_and_variant_provenance(self):
        product_ids = {p["product_id"] for p in self.products}
        variants = [v for v in CATALOG["variants"] if v.get("product_id") in product_ids]
        self.assertEqual(len(self.products), 223)
        self.assertEqual(len(variants), 214)
        self.assertTrue(all(v.get("source_evidence_url") for v in variants))
        self.assertFalse(any("fragrantica.com" in v["source_evidence_url"].lower() for v in variants))

    def test_visible_official_perfume_oil_range_is_present(self):
        expected = (
            "Maya", "Johayna Purple", "Amber Pure", "Arabian Treasure", "Anabia Red",
            "Anabia Blue", "Oud & Musk", "Pure Musk", "Johayna Green", "Kayaan Silver",
            "Kayaan Gold", "Pink Musk", "Purple Musk", "Malika Red", "Malika Green",
            "Hareem Al Sultan Blue", "Hareem Al Sultan Gold", "Hareem Al Sultan Silver",
            "Mukhalath Ma'a Ward Taiba", "Rimaal Brown", "Rimaal Green", "Haneen Gold",
            "Haneen Rose Gold", "Jameel", "Zainab", "Roohi Wa Roohak Gold", "Shamookh Gold",
            "Alf Wardaat", "Al Riyan", "Ibhaar", "Roohi Wa Roohak Silver", "Ghazlaan",
            "Mibraak", "Raniya", "Shamookh Silver", "Aaliya",
        )
        names = {normalized(p["canonical_name"]) for p in self.products}
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(normalized(name), names)

    def test_visible_la_fede_collection_range_is_present(self):
        expected = (
            "La Fede Intoxicate Mystique", "La Fede Edge Intense", "La Fede Edge Original",
            "La Fede Symbol of Love", "La Fede Symbol of Power", "La Fede Choco Brown",
            "La Fede White Forest Strawberry", "La Fede Celeste Toffee", "La Fede Celeste Fluer",
            "La Fede Celeste Joice", "La Fede Celeste Aqua", "La Fede Intoxicate Blue Elixir",
            "La Fede Intoxicate", "La Fede Aura Manga Splash", "La Fede Aura Pista Dessert",
            "La Fede Opera Noir L'Or", "La Fede Opera Rose L'Or", "La Fede Crystallia Imperio",
            "La Fede Crystallia Primaso", "La Fede Magnum Extreme Blue", "La Fede Magnum Wild Green",
            "La Fede Magnum Gold Edition", "La Fede Magnum Silver Edition", "La Fede Aura Kiss of Rose",
            "La Fede Aura Crisp Flower", "La Fede Belle Reve Segrato Viola",
            "La Fede Bella Reve Dolce Flore", "La Fede Statesman", "La Fede First Lady",
            "La Fede Kingsman", "La Fede Miss Premiere", "La Fede Code Marron Oud",
            "La Fede Code Rouge Amour", "La Fede Code Verde Sublime", "Code Viola Nectar",
            "La Fede Uno Intimo",
        )
        names = {normalized(p["canonical_name"]) for p in self.products}
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(normalized(name), names)

    def test_hareem_al_sultan_gold_is_an_oil_not_a_spray(self):
        product = next(p for p in self.products if p["canonical_name"] == "Hareem Al Sultan Gold")
        self.assertEqual(product.get("concentration"), "Perfume Oil")
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertTrue(any(v.get("size_ml") == 35 and v.get("concentration") == "Perfume Oil" and v.get("source_evidence_url") for v in variants))

    def test_saqr_al_badiya_concentration_is_not_guessed(self):
        product = next(p for p in self.products if p["canonical_name"] == "Saqr Al Badiya")
        self.assertIsNone(product.get("concentration"))
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertTrue(any(v.get("size_ml") == 100 and not v.get("concentration") for v in variants))

    def test_private_blend_tobac_extra_is_distinct_from_private_blend(self):
        private_blend = next(p for p in self.products if p["canonical_name"] == "Private Blend")
        tobac = next(p for p in self.products if p["canonical_name"] == "Private Blend Tobac Extra")
        self.assertNotEqual(private_blend["product_id"], tobac["product_id"])
        self.assertTrue(any(v.get("product_id") == tobac["product_id"] and v.get("size_ml") == 100 and v.get("concentration") == "Extrait de Parfum" for v in CATALOG["variants"]))
        self.assertFalse(any(v.get("product_id") == private_blend["product_id"] and v.get("size_ml") == 100 and v.get("concentration") == "Extrait de Parfum" for v in CATALOG["variants"]))


    def test_pure_musk_has_separate_oil_and_edp_variants(self):
        product = next(p for p in self.products if p["canonical_name"] == "Pure Musk")
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertTrue(any(v.get("size_ml") == 20 and v.get("concentration") == "Perfume Oil" for v in variants))
        self.assertTrue(any(v.get("size_ml") == 100 and v.get("concentration") == "Eau de Parfum" for v in variants))
        self.assertIsNone(product.get("concentration"))

    def test_rasayel_vid_concentration_remains_unspecified(self):
        product = next(p for p in self.products if p["canonical_name"] == "Rasayel Vid")
        self.assertIsNone(product.get("concentration"))
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertTrue(any(v.get("size_ml") == 100 and not v.get("concentration") and v.get("source_evidence_url") for v in variants))

    def test_alf_wardaat_is_a_30ml_perfume_oil_with_spelling_alias(self):
        product = next(p for p in self.products if p["canonical_name"] == "Alf Wardaat")
        self.assertIn("Alf Wardat", product.get("aliases", []))
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertTrue(any(v.get("size_ml") == 30 and v.get("concentration") == "Perfume Oil" and v.get("source_evidence_url") for v in variants))

    def test_hareem_al_sultan_blue_is_a_35ml_perfume_oil(self):
        product = next(p for p in self.products if p["canonical_name"] == "Hareem Al Sultan Blue")
        variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
        self.assertTrue(any(v.get("size_ml") == 35 and v.get("concentration") == "Perfume Oil" and v.get("source_evidence_url") for v in variants))

    def test_extended_la_fede_collection_products_are_present(self):
        expected = (
            "Uno Durable", "Uno Lusso", "La Fede Lavish Luna", "La Fede Lavish Rouge",
            "La Fede Lavish Blush", "La Fede Aura Vanilla Milk",
        )
        names = {normalized(p["canonical_name"]) for p in self.products}
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(normalized(name), names)

    def test_oil_family_registry_contains_the_reconciled_oil_products(self):
        family = next(f for f in self.families if f["family_id"] == "khadlaj_perfume_oils")
        self.assertEqual(len(family["products"]), 42)
        family_names = {normalized(p["canonical_name"]) for p in family["products"]}
        expected = ("Johayna Purple", "Kayaan Silver", "Malika Green", "Mibraak", "Zainab")
        for name in expected:
            with self.subTest(name=name):
                self.assertIn(normalized(name), family_names)

if __name__ == "__main__":
    unittest.main()

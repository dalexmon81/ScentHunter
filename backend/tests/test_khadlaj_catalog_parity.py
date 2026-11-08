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
        self.assertEqual(len([p for p in self.products if p["family_id"] == sprays["family_id"]]), 61)
        self.assertGreater(len(sprays["products"]), 0)

    def test_perfume_oil_identity_is_not_recast_as_a_spray_variant(self):
        maya = next(p for p in self.products if p["canonical_name"] == "Maya")
        self.assertEqual(maya.get("formats_ml"), [20])
        self.assertEqual(maya.get("concentration"), "Perfume Oil")
        variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") == maya["product_id"]
        ]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0].get("size_ml"), 20)
        self.assertEqual(variants[0].get("concentration"), "Perfume Oil")



    def test_all_khadlaj_variants_have_source_evidence_and_no_duplicate_skus(self):
        ids = {p["product_id"] for p in self.products}
        variants = [v for v in CATALOG["variants"] if v.get("product_id") in ids]
        self.assertEqual(len(variants), 226)
        self.assertTrue(all(v.get("source_evidence_url") for v in variants))
        keys = [(v["product_id"], v["size_ml"], v.get("concentration")) for v in variants]
        self.assertEqual(len(keys), len(set(keys)))

    def test_musk_pure_musk_blend_creation_of_iqbal_is_an_alias_not_a_second_identity(self):
        rows = [p for p in self.products if p["canonical_name"] == "Musk Pure Musk Blend"]
        self.assertEqual(len(rows), 1)
        self.assertIn("Musk Pure Musk Blend Creation of Iqbal", rows[0].get("aliases", []))
        self.assertFalse(any(p["canonical_name"] == "Musk Pure Musk Blend Creation of Iqbal" for p in self.products))

    def test_rasayel_vid_is_edp_and_saqr_concentration_remains_unset(self):
        rasayel = next(p for p in self.products if p["canonical_name"] == "Rasayel Vid")
        self.assertEqual(rasayel.get("concentration"), "Eau de Parfum")
        rasayel_variants = [v for v in CATALOG["variants"] if v.get("product_id") == rasayel["product_id"]]
        self.assertEqual(len(rasayel_variants), 1)
        self.assertEqual(rasayel_variants[0].get("concentration"), "Eau de Parfum")
        saqr = next(p for p in self.products if p["canonical_name"] == "Saqr Al Badiya")
        self.assertEqual(saqr.get("formats_ml"), [100])
        self.assertNotIn("concentration", saqr)
        saqr_variants = [v for v in CATALOG["variants"] if v.get("product_id") == saqr["product_id"]]
        self.assertEqual(len(saqr_variants), 1)
        self.assertNotIn("concentration", saqr_variants[0])


if __name__ == "__main__":
    unittest.main()

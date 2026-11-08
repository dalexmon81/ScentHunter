"""Regression tests for Bujairami UAE official product-detail evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

OFFICIAL_DETAIL_PAGES = {
    "Absolute Power": "https://bujairami.ae/products/absolute-power-inspired-by-le-male-elixir-absolu-jean-paul-gaultier",
    "ACE": "https://bujairami.ae/products/ace-inspired-by-uomo-born-in-roma-coral-fantasy-valentino",
    "Agha": "https://bujairami.ae/products/agha-inspired-by-althair-from-parfums-de-marly",
    "Apex": "https://bujairami.ae/products/apex-inspired-by-amiri-arabian-oud-extrait",
    "Blush": "https://bujairami.ae/products/blush-inspired-by-good-girl-blush-carolina-herrera",
    "Booz Extreme": "https://bujairami.ae/products/booz-extreme",
    "Boss Life": "https://bujairami.ae/products/boss-life-inspired-by-outlands-from-amouage",
    "Boujee": "https://bujairami.ae/products/boujee-inspired-by-attrape-reves-from-louis-vuitton",
    "Candy Carousel": "https://bujairami.ae/products/candy-carousel-inspired-by-l-eau-de-parfum-from-cirque-du-soleil",
    "Dubai Crush": "https://bujairami.ae/products/dubai-crush-original-creation",
}


class BujairamiUAEDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in CATALOG["products"] if p.get("brand") == "Bujairami"]
        cls.by_name = {p["canonical_name"]: p for p in cls.products}

    def test_existing_identities_are_upgraded_without_duplicates(self):
        self.assertEqual(len(self.products), 671)
        for name in OFFICIAL_DETAIL_PAGES:
            with self.subTest(name=name):
                self.assertIn(name, self.by_name)
                self.assertEqual(sum(p["canonical_name"] == name for p in self.products), 1)

    def test_ten_names_have_individual_first_party_product_evidence(self):
        for name, url in OFFICIAL_DETAIL_PAGES.items():
            with self.subTest(name=name):
                product = self.by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["family_id"], "bujairami_catalog")

    def test_no_unverified_size_or_concentration_is_added(self):
        for name in OFFICIAL_DETAIL_PAGES:
            with self.subTest(name=name):
                product = self.by_name[name]
                self.assertNotIn("formats_ml", product)
                self.assertNotIn("concentration", product)

    def test_cumulative_catalog_and_bujairami_variants_are_preserved(self):
        self.assertEqual(len(CATALOG["products"]), 2743)
        self.assertEqual(len(CATALOG["variants"]), 717)
        product_ids = {p["product_id"] for p in self.products}
        variants = [v for v in CATALOG["variants"] if v.get("product_id") in product_ids]
        self.assertEqual(len(variants), 8)
        self.assertEqual(len({v["variant_id"] for v in variants}), 8)


if __name__ == "__main__":
    unittest.main()

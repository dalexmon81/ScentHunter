"""Regression checks for Bujairami official original-creation detail evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

OFFICIAL_DETAIL_PAGES = {
    "Ruthless Vanilla": "https://bujairami.com.au/products/ruthless-vanilla-original-creation",
    "The Aftermath": "https://bujairami.com.au/products/the-aftermath-by-bujairami-for-men-original-creation",
    "Her": "https://bujairami.com.au/products/her",
    "Mohabbat": "https://bujairami.com.au/products/mohabbat-original-creation",
}


class BujairamiOriginalDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in CATALOG["products"] if p.get("brand") == "Bujairami"]
        cls.by_name = {p["canonical_name"]: p for p in cls.products}

    def test_existing_canonical_identities_are_upgraded_not_duplicated(self):
        self.assertEqual(len(self.products), 671)
        for name in OFFICIAL_DETAIL_PAGES:
            with self.subTest(name=name):
                self.assertIn(name, self.by_name)
                self.assertEqual(sum(p["canonical_name"] == name for p in self.products), 1)

    def test_four_originals_have_individual_first_party_product_evidence(self):
        for name, url in OFFICIAL_DETAIL_PAGES.items():
            with self.subTest(name=name):
                product = self.by_name[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["family_id"], "bujairami_catalog")

    def test_no_size_or_concentration_is_inferred_from_detail_pages(self):
        for name in OFFICIAL_DETAIL_PAGES:
            with self.subTest(name=name):
                product = self.by_name[name]
                self.assertNotIn("formats_ml", product)
                self.assertNotIn("concentration", product)

    def test_cumulative_bujairami_variants_remain_unchanged(self):
        product_ids = {p["product_id"] for p in self.products}
        variants = [v for v in CATALOG["variants"] if v.get("product_id") in product_ids]
        self.assertEqual(len(variants), 8)
        self.assertEqual(len({v["variant_id"] for v in variants}), 8)


if __name__ == "__main__":
    unittest.main()

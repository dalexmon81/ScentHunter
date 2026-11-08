"""Regression checks for Bujairami original-creation reconciliation."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Australian Watermelon", "Top Life", "Luxe Noir", "Snow White", "Down Under",
    "HIM", "Gold Coast", "Coco Dream", "Riverina", "Aussie Glow", "Madeira Cake",
    "Apple Crumble", "Knefeh", "Love Spell", "King Street", "The F*ck Up",
    "Harbour Tea", "Queens Avenue", "Pistachio Cake", "Woolloomooloo",
    "Cherry Cherry Lady",
}


class BujairamiOriginalsTests(unittest.TestCase):
    def test_reconciled_originals_have_unique_canonical_identities(self):
        products = [p for p in CATALOG["products"] if p.get("brand") == "Bujairami"]
        selected = [p for p in products if p.get("canonical_name") in EXPECTED]
        self.assertEqual({p["canonical_name"] for p in selected}, EXPECTED)
        self.assertEqual(len(selected), len(EXPECTED))

    def test_detail_page_and_collection_evidence_are_not_conflated(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Bujairami"}
        for name in EXPECTED - {"The F*ck Up"}:
            self.assertEqual(products[name]["identity_status"], "source_verified_name")
            self.assertIn("/products/", products[name]["source_url"])
        listed = products["The F*ck Up"]
        self.assertEqual(listed["identity_status"], "source_listed_name")
        self.assertIn("/collections/originals", listed["source_url"])

    def test_love_spell_sizes_are_explicit_variants(self):
        product_id = "SH-BUJAIRAMI-LOVE-SPELL"
        variants = [v for v in CATALOG["variants"] if v["product_id"] == product_id]
        by_size = {v["size_ml"]: v for v in variants}
        self.assertTrue({50, 100}.issubset(by_size))
        self.assertIn("/products/love-spell-original-creation-50ml", by_size[50]["source_url"])
        self.assertIn("/products/love-spell-original-creation", by_size[100]["source_url"])


if __name__ == "__main__":
    unittest.main()

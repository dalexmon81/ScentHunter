"""Regression checks for Maison Alhambra individual product-page evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Afro Leather": (80, "6291108736081", "https://maisonalhambra-usa.com/products/maison-alhambra-afro-leather-eau-de-parfum-for-everyone"),
    "Alpine Homme Sport": (100, "6291108735879", "https://maisonalhambra-usa.com/products/maison-alhambra-alpine-homme-sport-eau-de-parfum-for-men"),
    "Anarch": (100, "6291107459080", "https://maisonalhambra-usa.com/products/maison-alhambra-anarch-eau-de-parfum-for-everyone"),
    "Anchor Black": (100, "6291108730058", "https://maisonalhambra-usa.com/products/maison-alhambra-anchor-black-eau-de-parfum-for-men"),
    "Aromatic Rouge": (100, "6291107459097", "https://maisonalhambra-usa.com/products/maison-alhambra-aromatic-rouge-eau-de-parfum-for-women"),
    "Athena": (100, "6290360599243", "https://maisonalhambra-usa.com/products/maison-alhambra-athena-eau-de-parfum-for-women"),
    "Aura D'Eclat": (100, "6291107459103", "https://maisonalhambra-usa.com/products/maison-alhambra-aura-declat-eau-de-parfum-for-women"),
    "Avant Ruby": (100, "6290362343134", "https://maisonalhambra-usa.com/products/maison-alhambra-avant-ruby-eau-de-parfum-for-women"),
    "Avant Silk": (100, "6290362340768", "https://maisonalhambra-usa.com/products/maison-alhambra-avant-silk-eau-de-parfum-for-everyone"),
    "Baroque Satin Oud": (100, "6291108736050", "https://maisonalhambra-usa.com/products/maison-alhambra-baroque-satin-oud-eau-de-parfum-for-everyone"),
    "Berlinetta": (100, "6291107459158", "https://maisonalhambra-usa.com/products/maison-alhambra-berlinetta-eau-de-parfum-for-everyone"),
    "Black Origami": (100, "6291108730065", "https://maisonalhambra-usa.com/products/maison-alhambra-black-origami-eau-de-parfum-for-everyone"),
}


class MaisonAlhambraDetailPageHarvestTests(unittest.TestCase):
    def test_existing_identities_have_individual_page_evidence_and_exact_variants(self):
        products = {
            row.get("canonical_name") or row.get("name"): row
            for row in CATALOG.get("products", [])
            if (row.get("brand_name") or row.get("brand")) == "Maison Alhambra"
        }
        variants = CATALOG.get("variants", [])
        self.assertEqual(len(EXPECTED), 12)
        for name, (size_ml, gtin, source_url) in EXPECTED.items():
            with self.subTest(name=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertEqual(product.get("source_evidence_url"), source_url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertIn(size_ml, product.get("formats_ml", []))
                matching = [
                    row for row in variants
                    if row.get("product_id") == product["product_id"]
                    and row.get("size_ml") == size_ml
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matching[0].get("gtin"), gtin)
                self.assertEqual(matching[0].get("source_evidence_url"), source_url)
                self.assertEqual(len(gtin), 13)
                self.assertTrue(gtin.isdigit())


if __name__ == "__main__":
    unittest.main()

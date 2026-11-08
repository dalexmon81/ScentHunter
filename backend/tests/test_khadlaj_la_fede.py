"""Regression tests for the full official Khadlaj La Fede product family."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "La Fede Intoxicate Mystique": {
        "size_ml": 100,
        "concentration": "Extrait de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-intoxicate-blue-elixir-100-ml-eau-de-parfume-spray-for-men-copy"
    },
    "La Fede Celebrity Crush": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-celebrity-crush-100ml-eau-de-parfum"
    },
    "La Fede Celebrity Fame": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-celebrity-fame-100ml-eau-de-parfum"
    },
    "La Fede Aura Crisp Flower": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-aura-crisp-flower-100-ml-edp-sproay-for-women"
    },
    "La Fede Aura Kiss of Rose": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-aura-kiss-of-rose-100-ml-edp-spray-for-women"
    },
    "La Fede Aura Manga Splash": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-aura-manga-splash-100-ml-edp-spray-for-women"
    },
    "La Fede Aura Pista Dessert": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-aura-manga-splash-100-ml-edp-spray-for-women-copy"
    },
    "La Fede Bella Reve Dolce Flore": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-bella-reev-dolce-flore-100-ml-edp-spray"
    },
    "La Fede Belle Reve Segrato Viola": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-belle-reve-segrato-viola-100-ml-edp-spray"
    },
    "La Fede Celeste Aqua": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-celeste-aqua-100-ml-eau-de-parfum-for-men-and-women"
    },
    "La Fede Celeste Fluer": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-celeste-fluer-100-ml-eau-de-parfum-for-women"
    },
    "La Fede Celeste Joice": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-celeste-joice-100-ml-eau-de-parfum-women-scents"
    },
    "La Fede Celeste Toffee": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-celeste-toffee-100-ml-eau-de-parfum"
    },
    "La Fede Choco Brown": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-choco-brown-100-ml-eau-de-parfum-for-women-dubai-kunafa-chocolate-inspired-scent"
    },
    "La Fede Crystallia Imperio": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-crystallia-imperio-100-ml-edp-spray"
    },
    "La Fede Crystallia Primaso": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-crystallia-primaso-100-ml-edp-spray"
    },
    "La Fede Edge Intense": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-edge-intense-100-ml-eau-de-parfum-for-unisex-scents-dubai-uae"
    },
    "La Fede Edge Original": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-edge-original-eau-de-parfum-for-women-copy"
    },
    "La Fede First Lady": {
        "size_ml": 75,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-first-spray-shop-online-best-price-in-dubai-uae"
    },
    "La Fede Intoxicate": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-intoxicate-100-ml-edp-spray"
    },
    "La Fede Intoxicate Blue Elixir": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-intoxicate-blue-elixir-100-ml-edp-spray-for-men-best-perfumes-dubai-uae-usa-uk-worldwide"
    },
    "La Fede Kingsman": {
        "size_ml": 75,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-kingsman-spray-shop-online-best-price-in-dubai-uae"
    },
    "La Fede Lavish Blush": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-best-sellers-edp-signature-scents/products/la-fede-lavish-blush-edp-spray-100-ml"
    },
    "La Fede Lavish Luna": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-best-sellers-edp-signature-scents/products/la-fede-lavish-edp-spray-100-ml"
    },
    "La Fede Lavish Rouge": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-best-sellers-edp-signature-scents/products/la-fede-lavish-rouge-edp-spray-100-ml"
    },
    "La Fede Magnum Extreme Blue": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-magnum-extreme-blue-100-ml-edp-spray"
    },
    "La Fede Magnum Gold Edition": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-magnum-gold-edition-100-ml-edp-spray"
    },
    "La Fede Magnum Silver Edition": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-magnum-silver-edition-100-ml-edp-spray"
    },
    "La Fede Magnum Wild Green": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-magnum-wild-green-100ml-edp-spray"
    },
    "La Fede Miss Premiere": {
        "size_ml": 75,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-miss-premeire-spray-shop-online-best-price-in-dubai-uae"
    },
    "La Fede Opera Noir L'Or": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-opera-noir-lor-100-ml-edp-spray"
    },
    "La Fede Opera Rose L'Or": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-opera-rose-lor-100-ml-edp-spray"
    },
    "La Fede Statesman": {
        "size_ml": 75,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-statesman-spray-shop-online-best-price-in-dubai-uae"
    },
    "La Fede Symbol of Love": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-symbol-of-love-100-ml-eau-de-parfum-for-women-scents-by-khadlaj"
    },
    "La Fede Symbol of Power": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-symbol-of-power-100-ml-eau-de-parfum-unisex-scents-by-khadlaj"
    },
    "La Fede White Forest Strawberry": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/la-fede-white-forest-strawberry-edp-for-women-best-gourmand-fragrance-dubai-online"
    }
}


class KhadlajLaFedeTests(unittest.TestCase):
    def setUp(self):
        self.products = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Khadlaj" and p.get("family_id") == "khadlaj_la_fede"
        ]
        self.family = next(
            f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_la_fede"
        )

    def test_all_registry_la_fede_identities_are_canonical(self):
        self.assertEqual({p["canonical_name"] for p in self.products}, set(EXPECTED))
        self.assertEqual(len(self.products), 36)
        self.assertEqual(len(self.family["products"]), 36)

    def test_each_product_has_its_own_official_detail_page(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p["canonical_name"] == name)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["formats_ml"], [expected["size_ml"]])

    def test_each_variant_matches_official_size_and_concentration(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p["canonical_name"] == name)
                variants = [
                    v for v in CATALOG["variants"]
                    if v["product_id"] == product["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], expected["size_ml"])
                self.assertEqual(variants[0]["concentration"], expected["concentration"])
                self.assertEqual(variants[0]["source_url"], expected["url"])

    def test_family_registry_formats_match_official_variants(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                row = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(expected["size_ml"], row.get("formats_ml", []))

    def test_la_fede_products_are_not_duplicated_in_other_khadlaj_families(self):
        canonical_names = {p["canonical_name"].casefold() for p in self.products}
        for family in REGISTRY["families"]:
            if family["family_id"] == "khadlaj_la_fede":
                continue
            names = {p["canonical_name"].casefold() for p in family.get("products", [])}
            self.assertFalse(names & canonical_names)

    def test_celeste_fleur_official_spelling_is_an_alias(self):
        product = next(p for p in self.products if p["canonical_name"] == "La Fede Celeste Fluer")
        self.assertIn("La Fede Celeste Fleur", product["aliases"])
        row = next(p for p in self.family["products"] if p["canonical_name"] == "La Fede Celeste Fluer")
        self.assertIn("La Fede Celeste Fleur", row["aliases"])

    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()

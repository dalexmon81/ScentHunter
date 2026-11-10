"""Official Maison Alhambra women's detail-page batch, 10 November 2026."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Mia Dolcezza Verde": {"product_id": "SH-MAISON-ALHAMBRA-64f85f4c", "variant_id": "SHV-SH-MAISON-ALHAMBRA-64f85f4c-100-WOMEN", "gtin": "6290362342533", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-her/products/maison-alhambra-mia-dolcezza-verde-eau-de-parfum-for-women", "size_ml": 100},
    "Luxe Chic": {"product_id": "SH-MAISON-ALHAMBRA-385ad61e", "variant_id": "SHV-SH-MAISON-ALHAMBRA-385ad61e-100-WOMEN", "gtin": "6290362341147", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-her/products/maison-alhambra-luxe-chic-eau-de-parfum-for-women", "size_ml": 100},
    "Mia Dolcezza": {"product_id": "SH-MAISON-ALHAMBRA-b8de377a", "variant_id": "SHV-SH-MAISON-ALHAMBRA-b8de377a-100-WOMEN", "gtin": "6290362340560", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-her/products/maison-alhambra-mia-dolcezza-eau-de-parfum-for-women", "size_ml": 100},
    "Florenza": {"product_id": "SH-MAISON-ALHAMBRA-9b84baba", "variant_id": "SHV-SH-MAISON-ALHAMBRA-9b84baba-100-WOMEN", "gtin": "6291107459202", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-her/products/maison-alhambra-florenza-eau-de-parfum-for-women", "size_ml": 100},
    "III L'Impressio": {"product_id": "SH-MAISON-ALHAMBRA-50b61ede", "variant_id": "SHV-SH-MAISON-ALHAMBRA-50b61ede-100-WOMEN", "gtin": "6291108730164", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-her/products/maison-alhambra-limpressio-iii-eau-de-parfum-for-women", "size_ml": 100},
    "Pink Velvet": {"product_id": "SH-MAISON-ALHAMBRA-PINK-VELVET", "variant_id": "SHV-SH-MAISON-ALHAMBRA-PINK-VELVET-80-WOMEN", "gtin": "6290362343226", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-her/products/maison-alhambra-pink-velvet-eau-de-parfum-for-women", "size_ml": 80},
}


class MaisonAlhambraWomensDetailBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(row for row in REGISTRY["families"] if row.get("family_id") == "maison_alhambra_catalog")

    def test_official_pages_upgrade_or_create_exact_canonical_identities(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in self.products if p.get("brand_name", p.get("brand")) == "Maison Alhambra" and p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                p = rows[0]
                self.assertEqual(p.get("product_id"), expected["product_id"])
                self.assertEqual(p.get("identity_status"), "source_verified_name")
                self.assertEqual(p.get("source_url"), expected["url"])
                self.assertEqual(p.get("source_product_url"), expected["url"])
                self.assertEqual(p.get("source_evidence_url"), expected["url"])
                self.assertEqual(p.get("formats_ml"), [expected["size_ml"]])
                self.assertEqual(p.get("concentration"), "Eau de Parfum")
                self.assertEqual(p.get("gender"), "Women")
                self.assertEqual(p.get("gtins"), [expected["gtin"]])

    def test_each_product_has_one_official_variant_with_exact_size_and_gtin(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [v for v in self.variants if v.get("variant_id") == expected["variant_id"]]
                self.assertEqual(len(rows), 1)
                v = rows[0]
                self.assertEqual(v.get("product_id"), expected["product_id"])
                self.assertEqual(v.get("size_ml"), expected["size_ml"])
                self.assertEqual(v.get("concentration"), "Eau de Parfum")
                self.assertEqual(v.get("gtin"), expected["gtin"])
                self.assertEqual(v.get("gender"), "Women")
                self.assertEqual(v.get("source_url"), expected["url"])
                self.assertEqual(v.get("source_evidence_url"), expected["url"])

    def test_family_registry_has_one_matching_size_entry_per_product(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [r for r in self.family["products"] if r.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [expected["size_ml"]])

    def test_global_product_variant_gtin_uniqueness_and_no_orphans(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        known = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))

    def test_iii_l_impressio_official_title_is_preserved_as_alias(self):
        product = next(p for p in self.products if p.get("product_id") == EXPECTED["III L'Impressio"]["product_id"])
        self.assertIn("L'impressio III", product.get("aliases", []))
        family_row = next(r for r in self.family["products"] if r.get("canonical_name") == "III L'Impressio")
        self.assertIn("L'impressio III", family_row.get("aliases", []))

    def test_no_commercial_offer_fields_are_added_to_variants(self):
        forbidden = {"price", "price_amount", "currency", "availability", "stock", "in_stock", "offer_url", "retailer", "store_id", "shipping_cost"}
        ids = {v["product_id"] for v in EXPECTED.values()}
        for variant in self.variants:
            if variant.get("product_id") in ids:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()

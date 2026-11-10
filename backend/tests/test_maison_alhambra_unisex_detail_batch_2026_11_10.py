"""Official Maison Alhambra unisex detail-page batch, 10 November 2026."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Luxe Gold": {"product_id": "SH-MAISON-ALHAMBRA-ad36ea7f", "variant_id": "SHV-SH-MAISON-ALHAMBRA-ad36ea7f-100-UNISEX", "gtin": "6290362341161", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-luxe-gold-eau-de-parfum-for-everyone", "size_ml": 100},
    "Luxe Emerald": {"product_id": "SH-MAISON-ALHAMBRA-baa24aeb", "variant_id": "SHV-SH-MAISON-ALHAMBRA-baa24aeb-100-UNISEX", "gtin": "6290362341109", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-luxe-emerald-eau-de-parfum-for-everyone", "size_ml": 100},
    "Flaming Elixir": {"product_id": "SH-MAISON-ALHAMBRA-df0e6458", "variant_id": "SHV-SH-MAISON-ALHAMBRA-df0e6458-80-UNISEX", "gtin": "6290360599205", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-flaming-elixir-eau-de-parfum-for-everyone", "size_ml": 80},
    "Luxe Journey": {"product_id": "SH-MAISON-ALHAMBRA-98516a17", "variant_id": "SHV-SH-MAISON-ALHAMBRA-98516a17-100-UNISEX", "gtin": "6290362341116", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-luxe-journey-eau-de-parfum-for-everyone", "size_ml": 100},
    "Luxe Blanc": {"product_id": "SH-MAISON-ALHAMBRA-1433f2ad", "variant_id": "SHV-SH-MAISON-ALHAMBRA-1433f2ad-100-UNISEX", "gtin": "6290362341093", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-luxe-blanc-eau-de-parfum-for-everyone", "size_ml": 100},
    "Luxe Street": {"product_id": "SH-MAISON-ALHAMBRA-d09579da", "variant_id": "SHV-SH-MAISON-ALHAMBRA-d09579da-100-UNISEX", "gtin": "6290362341154", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-luxe-street-eau-de-parfum-for-everyone", "size_ml": 100},
    "Spectrum": {"product_id": "SH-MAISON-ALHAMBRA-SPECTRUM", "variant_id": "SHV-SH-MAISON-ALHAMBRA-SPECTRUM-100-UNISEX", "gtin": "6290362340690", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-spectrum-eau-de-parfum-for-everyone", "size_ml": 100},
    "Renee Carmine": {"product_id": "SH-MAISON-ALHAMBRA-RENEE-CARMINE", "variant_id": "SHV-SH-MAISON-ALHAMBRA-RENEE-CARMINE-100-UNISEX", "gtin": "6290362340706", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-renee-carmine-eau-de-parfum-for-everyone", "size_ml": 100},
    "Smoky Touch": {"product_id": "SH-MAISON-ALHAMBRA-SMOKY-TOUCH", "variant_id": "SHV-SH-MAISON-ALHAMBRA-SMOKY-TOUCH-80-UNISEX", "gtin": "6290362343240", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-smoky-touch-eau-de-parfum-for-everyone", "size_ml": 80},
    "Pacific Blue": {"product_id": "SH-MAISON-ALHAMBRA-PACIFIC-BLUE", "variant_id": "SHV-SH-MAISON-ALHAMBRA-PACIFIC-BLUE-80-UNISEX", "gtin": "6291108735763", "url": "https://maisonalhambra-usa.com/collections/unisex-fragrance/products/maison-alhambra-pacific-blue-eau-de-parfum-for-everyone", "size_ml": 80},
}


class MaisonAlhambraUnisexDetailBatchTests(unittest.TestCase):
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
                self.assertEqual(p.get("gender"), "Unisex")
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
                self.assertEqual(v.get("gender"), "Unisex")
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

    def test_variants_contain_no_commercial_offer_data(self):
        forbidden = {"price", "price_amount", "currency", "availability", "stock", "in_stock", "offer_url", "retailer", "store_id", "shipping_cost"}
        ids = {v["product_id"] for v in EXPECTED.values()}
        for variant in self.variants:
            if variant.get("product_id") in ids:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()

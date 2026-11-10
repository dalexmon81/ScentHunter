"""Official Maison Alhambra men's detail-page batch, 10 November 2026."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Galactic Men Intense": {"product_id": "SH-MAISON-ALHAMBRA-78c98479", "variant_id": "SHV-SH-MAISON-ALHAMBRA-78c98479-100-MEN", "gtin": "6290362340515", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-galactic-men-intense-eau-de-parfum-for-men"},
    "Jorge di Profumo": {"product_id": "SH-MAISON-ALHAMBRA-cda42a6b", "variant_id": "SHV-SH-MAISON-ALHAMBRA-cda42a6b-100-MEN", "gtin": "6291108730140", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-jorge-di-profumo-eau-de-parfum-for-men"},
    "Yeah": {"product_id": "SH-MAISON-ALHAMBRA-YEAH", "variant_id": "SHV-SH-MAISON-ALHAMBRA-YEAH-100-MEN", "gtin": "6291108730324", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-yeah-eau-de-parfum-for-men"},
    "Yeah! Man Parfum": {"product_id": "SH-MAISON-ALHAMBRA-YEAH-MAN-PARFUM", "variant_id": "SHV-SH-MAISON-ALHAMBRA-YEAH-MAN-PARFUM-100-MEN", "gtin": "6290360590745", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-yeah-man-parfum-eau-de-parfum-for-men"},
    "Toro Pour Homme Glace": {"product_id": "SH-MAISON-ALHAMBRA-TORO-POUR-HOMME-GLACE", "variant_id": "SHV-SH-MAISON-ALHAMBRA-TORO-POUR-HOMME-GLACE-100-MEN", "gtin": "6290362340942", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-toro-pour-homme-glace-eau-de-parfum-for-men"},
    "Your Touch Amber": {"product_id": "SH-MAISON-ALHAMBRA-YOUR-TOUCH-AMBER", "variant_id": "SHV-SH-MAISON-ALHAMBRA-YOUR-TOUCH-AMBER-100-MEN", "gtin": "6290362340973", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-your-touch-amber-eau-de-parfum-for-men"},
    "Opulence Leather": {"product_id": "SH-MAISON-ALHAMBRA-OPULENCE-LEATHER", "variant_id": "SHV-SH-MAISON-ALHAMBRA-OPULENCE-LEATHER-100-MEN", "gtin": "6291108730041", "url": "https://maisonalhambra-usa.com/collections/fragrances-for-him/products/maison-alhambra-opulence-leather-eau-de-parfum-for-men"},
}


class MaisonAlhambraMensDetailBatchTests(unittest.TestCase):
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
                self.assertEqual(p.get("formats_ml"), [100])
                self.assertEqual(p.get("concentration"), "Eau de Parfum")
                self.assertEqual(p.get("gender"), "Men")
                self.assertEqual(p.get("gtins"), [expected["gtin"]])

    def test_every_product_has_one_official_100ml_edp_variant(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [v for v in self.variants if v.get("variant_id") == expected["variant_id"]]
                self.assertEqual(len(rows), 1)
                v = rows[0]
                self.assertEqual(v.get("product_id"), expected["product_id"])
                self.assertEqual(v.get("size_ml"), 100)
                self.assertEqual(v.get("concentration"), "Eau de Parfum")
                self.assertEqual(v.get("gtin"), expected["gtin"])
                self.assertEqual(v.get("gender"), "Men")
                self.assertEqual(v.get("source_url"), expected["url"])
                self.assertEqual(v.get("source_evidence_url"), expected["url"])

    def test_family_registry_has_one_matching_100ml_entry_per_product(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                rows = [row for row in self.family["products"] if row.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [100])

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

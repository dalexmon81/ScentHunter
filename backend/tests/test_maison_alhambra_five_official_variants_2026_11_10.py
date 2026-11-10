"""Maison Alhambra official-source 100 ml EDP catalog batch."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Philos Pura": ("SH-MAISON-ALHAMBRA-PHILOS-PURA", "6291107459349", "https://maisonalhambra-usa.com/products/maison-alhambra-philos-pura-eau-de-parfum-for-everyone"),
    "Philos Messenger": ("SH-MAISON-ALHAMBRA-PHILOS-MESSENGER", "6290362340898", "https://maisonalhambra-usa.com/products/maison-alhambra-philos-messenger-eau-de-parfum-for-everyone"),
    "The Myth": ("SH-MAISON-ALHAMBRA-THE-MYTH", "6291108735626", "https://maisonalhambra-usa.com/products/maison-alhambra-the-myth-eau-de-parfum-for-everyone"),
    "Joyous Infini Oud": ("SH-MAISON-ALHAMBRA-JOYOUS-INFINI-OUD", "6290360590561", "https://maisonalhambra-usa.com/products/maison-alhambra-joyous-infini-oud-eau-de-parfum-for-everyone"),
    "Roman VII": ("SH-MAISON-ALHAMBRA-ROMAN-VII", "6291108735671", "https://maisonalhambra-usa.com/products/maison-alhambra-roman-vii-eau-de-parfum-for-everyone"),
}


class MaisonAlhambraOfficialFiveProductBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_five_new_canonical_identities_have_official_detail_sources(self):
        for name, (product_id, gtin, source) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name", p.get("brand")) == "Maison Alhambra"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("product_id"), product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("source_product_url"), source)
                self.assertEqual(product.get("source_evidence_url"), source)
                self.assertEqual(product.get("gender"), "Unisex")
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("gtins"), [gtin])

    def test_each_canonical_product_has_one_unique_100ml_edp_variant(self):
        all_gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        self.assertEqual(len(all_gtins), len(set(all_gtins)))
        for name, (product_id, gtin, source) in EXPECTED.items():
            with self.subTest(product=name):
                variants = [v for v in self.variants if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant.get("variant_id"), f"SHV-{product_id}-100-EDP")
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("gtin"), gtin)
                self.assertEqual(variant.get("source_url"), source)
                self.assertEqual(variant.get("source_evidence_url"), source)

    def test_maison_alhambra_family_registry_has_all_five_records(self):
        family = self.families["maison_alhambra_catalog"]
        for name in EXPECTED:
            with self.subTest(product=name):
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [100])

    def test_canonical_ids_variant_ids_gtins_and_parent_links_are_unique(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        known = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))

    def test_no_retail_offer_or_stock_fields_are_imported(self):
        forbidden = {"price", "currency", "availability", "stock", "shipping_cost", "retailer", "offer_url", "store_url"}
        selected = {value[0] for value in EXPECTED.values()}
        for product in self.products:
            if product.get("product_id") in selected:
                self.assertFalse(forbidden.intersection(product))
        for variant in self.variants:
            if variant.get("product_id") in selected:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()

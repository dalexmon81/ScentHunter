"""Official Khadlaj Shiyaaka and gourmand detail-page reconciliation."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = [
    {
        "name": "Shiyaaka Sky",
        "product_id": "SH-KHADLAJ-04a500ea",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/special-edition-shiyaaka-sky-100-ml",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range",
        "gtin": "6298043072694"
    },
    {
        "name": "Shiyaaka Shadow",
        "product_id": "SH-KHADLAJ-b23ae855",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/khadlaj-special-edition-shiyaaka-shadow-edp-men-fresh-fragrance-dubai-uae",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range",
        "gtin": "6291107979359"
    },
    {
        "name": "Shiyaaka Snow",
        "product_id": "SH-KHADLAJ-bbb43d66",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/special-edition-shiyaaka-snow-100-ml-eau-de-parfum-for-men",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range"
    },
    {
        "name": "Shiyaaka Blue",
        "product_id": "SH-KHADLAJ-20646841",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/shiyaaka-blue-100ml-shop-online-best-price-in-dubai-uae",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range"
    },
    {
        "name": "Shiyaaka Gold",
        "product_id": "SH-KHADLAJ-0aefd15f",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/shiyaaka-gold-100ml-spray-shop-online-best-price-in-dubai-uae",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range"
    },
    {
        "name": "Shiyaaka For Men",
        "product_id": "SH-KHADLAJ-b9170594",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/shiyaaka-for-men-spray-shop-online-best-price-in-dubai-uae",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range"
    },
    {
        "name": "Shiyaaka White",
        "product_id": "SH-KHADLAJ-a56e7c92",
        "url": "https://khadlaj-perfumes.com/collections/shiyaaka-range/products/shiyaaka-for-women-spray-shop-online-best-price-in-dubai-uae",
        "evidence": "https://khadlaj-perfumes.com/collections/shiyaaka-range"
    },
    {
        "name": "Private Blend Musk Ice",
        "product_id": "SH-KHADLAJ-dd1434f1",
        "url": "https://khadlaj-perfumes.com/collections/all/products/private-blend-musk-ice-extrait-de-parfum-100-ml-designer-fragrance",
        "evidence": "https://khadlaj-perfumes.com/collections/all/women"
    },
    {
        "name": "Biscotti Date Toffee",
        "product_id": "SH-KHADLAJ-75815e2a",
        "url": "https://khadlaj-perfumes.com/collections/all/products/biscotti-date-toffee-100-ml-extrait-de-parfum-spray-for-unisex-gourmand-lover-fragrances",
        "evidence": "https://khadlaj-perfumes.com/collections/all/women"
    },
    {
        "name": "Musk Pure Musk Blend",
        "product_id": "SH-KHADLAJ-04832397",
        "url": "https://khadlaj-perfumes.com/products/musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae",
        "evidence": "https://khadlaj-perfumes.com/products/musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae",
        "gtin": "6291107978154",
        "size_ml": 60,
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-KHADLAJ-04832397-60-000"
    }
]

class KhadlajShiyaakaGourmandOfficialDetailTests(unittest.TestCase):
    def test_official_detail_provenance_and_existing_variants(self):
        products = {p["product_id"]: p for p in CATALOG["products"]}
        variants = {v["product_id"]: v for v in CATALOG["variants"]}
        for item in EXPECTED:
            with self.subTest(name=item["name"]):
                product = products[item["product_id"]]
                variant = variants[item["product_id"]]
                self.assertEqual(product["canonical_name"], item["name"])
                self.assertEqual(product["brand"], "Khadlaj")
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_product_url"], item["url"])
                self.assertEqual(product["source_evidence_url"], item["evidence"])
                self.assertEqual(variant["source_url"], item["url"])
                self.assertEqual(variant["source_evidence_url"], item["url"])
                self.assertEqual(variant.get("gtin"), item.get("gtin"))
                if "size_ml" in item:
                    self.assertEqual(product["formats_ml"], [item["size_ml"]])
                    self.assertEqual(product["concentration"], item["concentration"])
                    self.assertEqual(variant["variant_id"], item["variant_id"])
                    self.assertEqual(variant["size_ml"], item["size_ml"])
                    self.assertEqual(variant["concentration"], item["concentration"])
                family_id = "khadlaj_catalog" if item["name"] in {"Private Blend Musk Ice", "Biscotti Date Toffee", "Musk Pure Musk Blend"} else "khadlaj_shiyaaka"
                family = next(f for f in REGISTRY["families"] if f["family_id"] == family_id)
                self.assertIn(item["name"], [p["canonical_name"] for p in family["products"]])

    def test_no_duplicate_ids_or_orphan_variants(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        known = set(product_ids)
        self.assertTrue(all(v["product_id"] in known for v in CATALOG["variants"]))

if __name__ == "__main__":
    unittest.main()

"""Regression tests for the cumulative official-source variant follow-up."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = [
    {
        "name": "1963",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-16266aa9",
        "variant_id": "SHV-SH-MAISON-ASRAR-16266aa9-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/1963-eau-de-perfum-100ml"
    },
    {
        "name": "Adorable",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-3d531ce4",
        "variant_id": "SHV-SH-MAISON-ASRAR-3d531ce4-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/adorable-eau-de-parfum-100-ml-for-women"
    },
    {
        "name": "Alonoud",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-9f818ff4",
        "variant_id": "SHV-SH-MAISON-ASRAR-9f818ff4-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/maison-asrar-alonoud-eau-de-parfum-100-ml-for-women"
    },
    {
        "name": "Basma",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-a39f5b0c",
        "variant_id": "SHV-SH-MAISON-ASRAR-a39f5b0c-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/maison-asrar-basma-eau-de-parfum-100-ml-unisex"
    },
    {
        "name": "Black",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-cc3d301b",
        "variant_id": "SHV-SH-MAISON-ASRAR-cc3d301b-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/black-eau-de-perfum-100ml"
    },
    {
        "name": "Bloom Bloom",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-41bd4808",
        "variant_id": "SHV-SH-MAISON-ASRAR-41bd4808-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/bloom-bloom-eau-de-parfum-100ml"
    },
    {
        "name": "Bonita",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-50f4c721",
        "variant_id": "SHV-SH-MAISON-ASRAR-50f4c721-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/bonita-eau-de-parfum-100ml"
    },
    {
        "name": "Casablanca",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-ad855115",
        "variant_id": "SHV-SH-MAISON-ASRAR-ad855115-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/casablanca-maison-asrar-eau-de-perfum-100ml"
    },
    {
        "name": "Emessa",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-3e2cdf7a",
        "variant_id": "SHV-SH-MAISON-ASRAR-3e2cdf7a-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/maison-asrar-emessa-eau-de-parfum-for-women"
    },
    {
        "name": "Fairy Tale",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-21a61d03",
        "variant_id": "SHV-SH-MAISON-ASRAR-21a61d03-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/fairy-tale-eau-de-perfum-100ml"
    },
    {
        "name": "Fakhama",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-e94219a7",
        "variant_id": "SHV-SH-MAISON-ASRAR-e94219a7-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/maison-asrar-fakhama-eau-de-parfum-100-ml-for-women"
    },
    {
        "name": "Fresh Iris",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-f778e873",
        "variant_id": "SHV-SH-MAISON-ASRAR-f778e873-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml"
    },
    {
        "name": "Gentle Oud",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-a5a7cc49",
        "variant_id": "SHV-SH-MAISON-ASRAR-a5a7cc49-80-EDP",
        "size": 80,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/maison-asrar-gentle-oud-eau-de-parfum-80-ml-for-men"
    },
    {
        "name": "Hamsat Gharam",
        "brand": "Maison Asrar",
        "product_id": "SH-MAISON-ASRAR-9b703ddc",
        "variant_id": "SHV-SH-MAISON-ASRAR-9b703ddc-100-EDP",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": null,
        "url": "https://maisonasrar.com/products/maison-asrar-hamsat-gharam-eau-de-parfum-100-ml-for-women"
    },
    {
        "name": "Nuha Cherry Blush",
        "brand": "Khadlaj",
        "product_id": "SH-KHADLAJ-37d5907b",
        "variant_id": "SHV-SH-KHADLAJ-37d5907b-85-000",
        "size": 85,
        "concentration": "Eau de Parfum",
        "gtin": "6291107979175",
        "url": "https://khadlaj-perfumes.com/products/nuha-cherry-blush-85-ml-edp-spray-for-women-online-shopping-uae"
    },
    {
        "name": "Onyx Gold",
        "brand": "Khadlaj",
        "product_id": "SH-KHADLAJ-6494ea68",
        "variant_id": "SHV-SH-KHADLAJ-6494ea68-100-000",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070140",
        "url": "https://khadlaj-perfumes.com/products/khadlaj-onyx-gold-100-ml-eau-de-parfum-for-men-luxury-perfume-online-dubai-uae"
    },
    {
        "name": "Titan",
        "brand": "Khadlaj",
        "product_id": "SH-KHADLAJ-ce6dbd60",
        "variant_id": "SHV-SH-KHADLAJ-ce6dbd60-100-000",
        "size": 100,
        "concentration": "Eau de Parfum",
        "gtin": "6298043070065",
        "url": "https://khadlaj-perfumes.com/products/khadlaj-titan-100-ml-eau-de-parfum-spray-for-men-refreshing-scents-to-buy-online-dubai-uae"
    }
]

class CumulativeOfficialVariantFollowupTests(unittest.TestCase):
    def test_products_variants_and_registry_are_aligned(self):
        products = {p["product_id"]: p for p in CATALOG["products"]}
        families = {f["family_id"]: f for f in REGISTRY["families"]}
        for item in EXPECTED:
            with self.subTest(name=item["name"]):
                product = products[item["product_id"]]
                self.assertEqual(product["canonical_name"], item["name"])
                self.assertEqual(product["brand"], item["brand"])
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_product_url"], item["url"])
                self.assertEqual(product["source_evidence_url"], item["url"])
                self.assertIn(item["size"], product["formats_ml"])
                self.assertEqual(product["concentration"], item["concentration"])
                variants = [v for v in CATALOG["variants"] if v["product_id"] == item["product_id"] and v["size_ml"] == item["size"] and v.get("concentration") == item["concentration"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], item["variant_id"])
                self.assertEqual(variant.get("gtin"), item["gtin"])
                self.assertEqual(variant["source_evidence_url"], item["url"])
                family_id = "maison_asrar_catalog" if item["brand"] == "Maison Asrar" else "khadlaj_catalog"
                family_product = next(p for p in families[family_id]["products"] if p["canonical_name"] == item["name"])
                self.assertIn(item["size"], family_product["formats_ml"])

    def test_catalog_integrity(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        product_id_set = set(product_ids)
        self.assertTrue(all(v["product_id"] in product_id_set for v in CATALOG["variants"]))
        tuples = [(v["product_id"], v["size_ml"], v.get("concentration")) for v in CATALOG["variants"]]
        self.assertEqual(len(tuples), len(set(tuples)))
        gtins = [v["gtin"] for v in CATALOG["variants"] if v.get("gtin")]
        self.assertEqual(len(gtins), len(set(gtins)))
        products_by_id = {p["product_id"]: p for p in CATALOG["products"]}
        for variant in CATALOG["variants"]:
            formats = products_by_id[variant["product_id"]].get("formats_ml")
            if formats:
                self.assertIn(variant["size_ml"], formats)

if __name__ == "__main__":
    unittest.main()

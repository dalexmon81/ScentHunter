"""Regression tests for newly verified Al Haramain and Khadlaj product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class VerifiedDetailPageAdditionsTests(unittest.TestCase):
    def test_verified_products_and_variants(self):
        expected = {
            ("Al Haramain", "Oud Nomad"): ("https://shop.alharamainperfumes.com/eu/haramain-oud-nomad-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            ("Al Haramain", "Conception"): ("https://shop.alharamainperfumes.com/eu/haramain-conception-100ml-eau-de-parfum.html", "Eau de Parfum", 100),
            ("Khadlaj", "Icon"): ("https://khadlaj-perfumes.com/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men", "Eau de Parfum", 100),
            ("Khadlaj", "Island Vanilla Dunes"): ("https://khadlaj-perfumes.com/products/khadlaj-island-vanilla-dunes-100-ml-extrait-de-parfum-spray-for-men", "Extrait de Parfum", 100),
            ("Khadlaj", "Cloud Candy"): ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/cloud-candy-100-ml-extrait-de-parfum-fruity-marshmallow-fragrance-for-women-to-shop-online-in-dubai-uae", "Extrait de Parfum", 100),
            ("Khadlaj", "Caffe Latte"): ("https://khadlaj-perfumes.com/products/caffe-latte-100-ml-extrait-de-parfum-spray", "Extrait de Parfum", 100),
        }
        products = {(p.get("brand"), p["canonical_name"]): p for p in CATALOG["products"]}
        for key, (url, concentration, size) in expected.items():
            with self.subTest(product=key):
                p = products[key]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["concentration"], concentration)
                self.assertEqual(p["formats_ml"], [size])
                variants = [v for v in CATALOG["variants"] if v["product_id"] == p["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], size)
                self.assertEqual(variants[0]["concentration"], concentration)
                self.assertEqual(variants[0]["source_evidence_url"], url)

    def test_new_al_haramain_products_are_in_family_registry(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "al_haramain_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue({"Oud Nomad", "Conception"}.issubset(names))

    def test_global_product_and_variant_ids_are_unique(self):
        pids = [p["product_id"] for p in CATALOG["products"]]
        vids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(vids), len(set(vids)))


if __name__ == "__main__":
    unittest.main()

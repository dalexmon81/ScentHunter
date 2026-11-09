"""Four new Maison Alhambra launches with official product-page evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Victorioso Heroic": ("SH-MAISON-ALHAMBRA-6df7df75", "https://maisonalhambra-usa.com/products/maison-alhambra-victorioso-heroic-eau-de-parfum-for-men", 100, "SHV-SH-MAISON-ALHAMBRA-6df7df75-100-000"),
    "Rose Origami": ("SH-MAISON-ALHAMBRA-b9f1e8eb", "https://maisonalhambra-usa.com/products/maison-alhambra-rose-origami-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-b9f1e8eb-100-000"),
    "Opera Rouge": ("SH-MAISON-ALHAMBRA-327c9c77", "https://maisonalhambra-usa.com/products/maison-alhambra-opera-rouge-eau-de-parfum-for-everyone", 100, "SHV-SH-MAISON-ALHAMBRA-327c9c77-100-000"),
    "Camille": ("SH-MAISON-ALHAMBRA-87c08c97", "https://maisonalhambra-usa.com/products/maison-alhambra-camille-eau-de-parfum-for-women", 100, "SHV-SH-MAISON-ALHAMBRA-87c08c97-100-000"),
}


class MaisonAlhambraFourLaunchesTests(unittest.TestCase):
    def test_four_new_launches_have_official_pages_and_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "maison_alhambra_catalog")
        for name, (product_id, url, size, variant_id) in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("brand_name") == "Maison Alhambra" and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("product_id"), product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), variant_id)
                self.assertEqual(variants[0].get("size_ml"), size)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [size])


if __name__ == "__main__":
    unittest.main()

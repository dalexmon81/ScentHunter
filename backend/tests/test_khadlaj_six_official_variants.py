"""Regression tests for nineteen Khadlaj official product-page variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Muse": ("SH-KHADLAJ-MUSE", 100, "Eau de Parfum", "6298043072748", "https://khadlaj-perfumes.com/collections/deals/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women"),
    "Sueno": ("SH-KHADLAJ-SUENO", 100, "Extrait de Parfum", "6298043072809", "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/sueno-100ml-extrait-de-parfum-for-women"),
    "Saraya": ("SH-KHADLAJ-SARAYA", 60, "Extrait de Parfum", "6298043072380", "https://khadlaj-perfumes.com/collections/flash-sale/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women"),
    "Qarar": ("SH-KHADLAJ-QARAR", 60, "Extrait de Parfum", "6298043071628", "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum"),
    "Ihthiraam": ("SH-KHADLAJ-IHTHIRAAM", 60, "Extrait de Parfum", "6298043072229", "https://khadlaj-perfumes.com/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance"),
    "Icon": ("SH-KHADLAJ-ICON", 100, "Eau de Parfum", "6298043071215", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men"),
    "Zayaan Silver": ("SH-KHADLAJ-ZAYAAN-SILVER", 100, "Eau de Parfum", "6298043070058", "https://khadlaj-perfumes.com/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men"),
    "Onyx Gold": ("SH-KHADLAJ-6494ea68", 100, "Eau de Parfum", "6298043070140", "https://khadlaj-perfumes.com/products/khadlaj-onyx-gold-100-ml-eau-de-parfum-for-men-luxury-perfume-online-dubai-uae"),
    "Peach Velvet": ("SH-KHADLAJ-PEACH-VELVET", 100, "Extrait de Parfum", "6298043070034", "https://khadlaj-perfumes.com/collections/all/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae"),
    "Strawberry Shake": ("SH-KHADLAJ-STRAWBERRY-SHAKE", 100, "Eau de Parfum", "6298043070652", "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/strawberry-shake-eau-de-parfum-spray-for-women-dubai-uae-online"),
    "Nafais Magrib": ("SH-KHADLAJ-NAFAIS-MAGRIB", 100, "Eau de Parfum", "6298043070010", "https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-nafais-magrib-100-ml-eau-de-parfum-for-men-women"),
    "Mansion": ("SH-KHADLAJ-MANSION", 100, "Eau de Parfum", "6298043070331", "https://khadlaj-perfumes.com/collections/unisex-1/products/mansion-eau-de-parfum-spray-for-unisex-scents-by-khadlaj-dubai-uae"),
    "Private Blend": ("SH-KHADLAJ-PRIVATE-BLEND", 100, "Extrait de Parfum", "6291107979403", "https://khadlaj-perfumes.com/collections/khadlaj-na-best-sellers/products/private-blend-tobac-extra-extrait-de-parfum-100-ml-for-men"),
    "Zayaan Gold": ("SH-KHADLAJ-ZAYAAN-GOLD", 100, "Eau de Parfum", "6298043070041", "https://my.khadlaj-perfumes.com/products/zayaan-gold-100-ml-eau-de-parfum-for-men"),
    "Nuha Cherry Blush": ("SH-KHADLAJ-37d5907b", 85, "Eau de Parfum", "6291107979175", "https://khadlaj-perfumes.myshopify.com/collections/khadlaj-na-best-sellers/products/nuha-cherry-blush-85-ml-edp-spray-for-women-online-shopping-uae"),
    "Oud Pour Leather": ("SH-KHADLAJ-OUD-POUR-LEATHER", 100, "Eau de Parfum", "6291107977843", "https://khadlaj-perfumes.com/products/oud-pour-leather-100ml-edp-spray-for-men-and-women"),
    "Nuha Bon Bon": ("SH-KHADLAJ-7ecbb58c", 85, "Eau de Parfum", "6298043070317", "https://khadlaj-perfumes.myshopify.com/collections/for-her/products/nuha-bon-bon-strawberry-vanilla-ice-cream-gourmand-perfume-for-women-online"),
    "Nuha Vanilla Pearl": ("SH-KHADLAJ-76dd12b7", 85, "Eau de Parfum", "6291107979182", "https://khadlaj-perfumes.com/collections/khadlaj-na-best-sellers/products/nuha-vanilla-pearl-85-ml-edp-spray-for-women-online-dubai-uae"),
    "Onyx Silver": ("SH-KHADLAJ-ce66d76f", 100, "Eau de Parfum", "6298043071161", "https://khadlaj-perfumes.com/products/khadlaj-onyx-silver-100-ml-eau-de-parfum-for-men-and-women-online-dubai-uae"),
}

class KhadlajOfficialVariantBatchTests(unittest.TestCase):
    def test_existing_canonical_products_are_source_verified(self):
        for name, (product_id, size, concentration, gtin, url) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj" and p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [size])
                self.assertEqual(product["concentration"], concentration)

    def test_each_product_has_one_gtin_backed_official_variant(self):
        for name, (product_id, size, concentration, gtin, url) in EXPECTED.items():
            with self.subTest(product=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], f"SHV-{product_id}-{size}-000")
                self.assertEqual(variant["size_ml"], size)
                self.assertEqual(variant["concentration"], concentration)
                self.assertEqual(variant["gtin"], gtin)
                self.assertEqual(variant["source_url"], url)
                self.assertEqual(variant["source_evidence_url"], url)

    def test_khadlaj_family_registry_has_one_canonical_sueno_row(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "khadlaj_catalog")
        sueno_rows = [p for p in family["products"] if p.get("canonical_name") in ("Sueno", "Sueño")]
        self.assertEqual(len(sueno_rows), 1)
        self.assertEqual(sueno_rows[0]["canonical_name"], "Sueno")
        self.assertIn("Sueño", sueno_rows[0].get("aliases", []))
        private_blend = next(p for p in family["products"] if p.get("canonical_name") == "Private Blend")
        self.assertIn("Private Blend Tobac Extra", private_blend.get("aliases", []))
        for name, (_, size, _, _, _) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].get("formats_ml"), [size])

if __name__ == "__main__":
    unittest.main()

"""Regression tests for twenty-six Khadlaj official product-page variants."""
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
    "Oud Pure Oud Barakat": ("SH-KHADLAJ-SPRAY-HARVEST-056", 60, "Eau de Parfum", "6291107979564", "https://khadlaj-perfumes.com/collections/unisex-1/products/oud-pure-oud-barakat-60-ml-master-perfumer-collection-edp-spray-for-men-women"),
    "Oud Pure Oud Galazaid": ("SH-KHADLAJ-SPRAY-HARVEST-057", 60, "Eau de Parfum", "6291107979588", "https://khadlaj-perfumes.com/products/oud-pure-oud-galazaid-60-ml-master-perfumer-collection-edp-spray-for-men-women"),
    "Oud Pure Oud Jumeirah": ("SH-KHADLAJ-SPRAY-HARVEST-058", 60, "Eau de Parfum", "6291107979595", "https://khadlaj-perfumes.myshopify.com/collections/khadlaj-na-best-sellers/products/oud-pure-oud-barakat-60-ml-master-perfumer-collection-edp-spray-for-men-women-copy"),
    "Fursan Brown": ("SH-KHADLAJ-SPRAY-HARVEST-065", 100, "Eau de Parfum", "6291107977768", "https://khadlaj-perfumes.com/products/khadlaj-fursan-brown-100-ml-edp-spray-perfume-for-him-and-her"),
    "Musk Pour Amber": ("SH-KHADLAJ-SPRAY-HARVEST-064", 100, "Eau de Parfum", "6291107977850", "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/musk-pour-amber-edp-spray-best-designer-perfume-for-women-online-dubai-uae"),
    "Sara": ("SH-KHADLAJ-SPRAY-HARVEST-066", 100, "Extrait de Parfum", "6291107978772", "https://khadlaj-perfumes.com/products/khadlaj-sara-100-ml-extrait-de-parfum-spray-for-women-best-price-dubai-uae"),
    "Valor Enigma": ("SH-KHADLAJ-SPRAY-HARVEST-082", 100, "Eau de Parfum", "6291107975979", "https://khadlaj-perfumes.com/collections/mens-perfumes/products/valor-enigma-100-ml-edp-spray"),
    "Le Prestige Empress": ("SH-KHADLAJ-SPRAY-HARVEST-071", 100, "Eau de Parfum", "6291107975948", "https://khadlaj-perfumes.com/products/le-prestige-empress-100-ml-edp-spray-elegant-women-perfume-online-dubai-uae"),
    "Le Prestige Bold": ("SH-KHADLAJ-SPRAY-HARVEST-072", 100, "Eau de Parfum", "6291107975924", "https://khadlaj-perfumes.com/collections/unisex-1/products/le-prestige-bold-100-ml-edp-spray-trending-perfume-for-women"),
    "Le Prestige Royal": ("SH-KHADLAJ-SPRAY-HARVEST-070", 100, "Eau de Parfum", "6291107975931", "https://khadlaj-perfumes.com/products/le-prestige-royal-100-ml-edp-spray"),
    "Empire Victor": ("SH-KHADLAJ-935bcf95", 100, "Eau de Parfum", "6291107975917", "https://khadlaj-perfumes.myshopify.com/collections/best-selling-perfumes/products/empire-victor-100-ml-edp-spray-best-perfume-for-women"),
    "Empire Empress": ("SH-KHADLAJ-SPRAY-HARVEST-083", 100, "Eau de Parfum", "6291107975894", "https://khadlaj-perfumes.com/products/empire-empress-100-ml-edp-spray-buy-top-women-perfume-online-dubai-uae"),
    "Empire Crown": ("SH-KHADLAJ-SPRAY-HARVEST-084", 100, "Eau de Parfum", "6291107975887", "https://khadlaj-perfumes.com/collections/unisex-1/products/empire-crown-100-ml-edp-spray-best-perfume-spray-for-men-online-dubai-uae"),
    "Empire Regent": ("SH-KHADLAJ-SPRAY-HARVEST-085", 100, "Eau de Parfum", "6291107975900", "https://khadlaj-perfumes.com/products/empire-regent-100-ml-edp-spray-luxury-perfume-for-men-and-women-dubai-uae"),
    "25 Integrity": ("SH-KHADLAJ-SPRAY-HARVEST-078", 100, "Eau de Parfum", "6291107975375", "https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-25-integrity-100-ml-edp-spray"),
    "25 Heritage": ("SH-KHADLAJ-SPRAY-HARVEST-077", 100, "Eau de Parfum", "6291107975368", "https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-25-heritage-100-ml-edp-spray"),
    "25 Loyalty": ("SH-KHADLAJ-SPRAY-HARVEST-076", 100, "Eau de Parfum", "6291107975382", "https://my.khadlaj-perfumes.com/products/khadlaj-25-loyalty-100-ml-edp-spray-best-women-perfume-to-shop-online-dubai-uae"),
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

    def test_family_registry_matches_each_products_family_and_size(self):
        for name, (product_id, size, _, _, _) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p.get("product_id") == product_id)
                family = next(f for f in REGISTRY["families"] if f.get("family_id") == product.get("family_id"))
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [size])
        main_family = next(f for f in REGISTRY["families"] if f.get("family_id") == "khadlaj_catalog")
        sueno_rows = [p for p in main_family["products"] if p.get("canonical_name") in ("Sueno", "Sueño")]
        self.assertEqual(len(sueno_rows), 1)
        self.assertEqual(sueno_rows[0]["canonical_name"], "Sueno")
        self.assertIn("Sueño", sueno_rows[0].get("aliases", []))
        private_blend = next(p for p in main_family["products"] if p.get("canonical_name") == "Private Blend")
        self.assertIn("Private Blend Tobac Extra", private_blend.get("aliases", []))

if __name__ == "__main__":
    unittest.main()

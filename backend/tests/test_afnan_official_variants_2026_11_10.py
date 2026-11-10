"""Thirteen Afnan bottle variants verified on official regional product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "9 AM Dive": ("SH-AFNAN-9e3c80fa", 100, "Eau de Parfum", "SHV-SH-AFNAN-9e3c80fa-100-EDP", "https://www.de.afnan.com/en/products/9-am-dive"),
    "Rare Reef": ("SH-AFNAN-e408d61b", 100, "Extrait de Parfum", "SHV-SH-AFNAN-e408d61b-100-EXTRAIT", "https://www.at.afnan.com/en/products/rare-reef"),
    "Turathi Brown Homme": ("SH-AFNAN-5cdc0bae", 90, "Eau de Parfum", "SHV-SH-AFNAN-5cdc0bae-90-EDP", "https://www.at.afnan.com/en/products/turathi-brown-homme"),
    "Historic Olmeda": ("SH-AFNAN-62b409e4", 100, "Eau de Parfum", "SHV-SH-AFNAN-62b409e4-100-EDP", "https://www.at.afnan.com/products/historic-olmeda"),
    "Mystique Bouquet": ("SH-AFNAN-4e32c3b3", 80, "Eau de Parfum", "SHV-SH-AFNAN-4e32c3b3-80-EDP", "https://www.de.afnan.com/en/products/mystique-bouquet"),
    "Supremacy Pink": ("SH-AFNAN-d587de8a", 100, "Eau de Parfum", "SHV-SH-AFNAN-d587de8a-100-EDP", "https://www.fr.afnan.com/products/supremacy-pink"),
    "Rare Carbon": ("SH-AFNAN-d0bee594", 100, "Eau de Parfum", "SHV-SH-AFNAN-d0bee594-100-EDP", "https://www.at.afnan.com/en/products/rare-carbon"),
    "Turathi Blue": ("SH-AFNAN-e9bc6ab8", 90, "Eau de Parfum", "SHV-SH-AFNAN-e9bc6ab8-90-EDP", "https://www.fr.afnan.com/products/turathi-blue-homme"),
    "Souvenir Floral Bouquet": ("SH-AFNAN-bdb31951", 100, "Eau de Parfum", "SHV-SH-AFNAN-bdb31951-100-EDP", "https://at.afnan.com/en/products/souvenir-floral-bouquet"),
    "Supremacy Gala": ("SH-AFNAN-387345b5", 90, "Extrait de Parfum", "SHV-SH-AFNAN-387345b5-90-EXTRAIT", "https://www.at.afnan.com/en/products/supremacy-gala"),
    "9 PM Rebel": ("SH-AFNAN-068d05a5", 100, "Eau de Parfum", "SHV-SH-AFNAN-068d05a5-100-EDP", "https://www.at.afnan.com/en/products/9-pm-rebel"),
    "9 PM Elixir": ("SH-AFNAN-69527fa0", 100, "Extrait de Parfum", "SHV-SH-AFNAN-69527fa0-100-EXTRAIT", "https://www.fr.afnan.com/products/9-pm-elixir"),
    "Supremacy Purple": ("SH-AFNAN-aa93308c", 100, "Eau de Parfum", "SHV-SH-AFNAN-aa93308c-100-EDP", "https://saudi.afnan.com/products/supremacy-purple"),
}


class AfnanOfficialVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(
            family for family in REGISTRY["families"]
            if family.get("family_id") == "afnan_catalog"
        )

    def test_existing_canonical_products_have_official_variants(self):
        for name, (product_id, size_ml, concentration, variant_id, url) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("product_id") == product_id)
                self.assertEqual(product["brand"], "Afnan")
                self.assertEqual(product["canonical_name"], name)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_product_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [size_ml])
                self.assertEqual(product["concentration"], concentration)
                variants = [v for v in self.variants if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], variant_id)
                self.assertEqual(variant["size_ml"], size_ml)
                self.assertEqual(variant["concentration"], concentration)
                self.assertEqual(variant["source_evidence_url"], url)
                self.assertNotIn("gtin", variant)

    def test_afnan_family_registry_formats_match_the_verified_variants(self):
        for name, (_, size_ml, _, _, _) in EXPECTED.items():
            with self.subTest(product=name):
                rows = [item for item in self.family["products"] if item.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [size_ml])

    def test_global_catalog_integrity_and_offer_separation(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        tuples = [(v.get("product_id"), v.get("size_ml"), v.get("concentration")) for v in self.variants]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        self.assertTrue(all(v.get("product_id") in known_products for v in self.variants))
        offer_fields = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        for variant in self.variants:
            self.assertTrue(offer_fields.isdisjoint(variant))


if __name__ == "__main__":
    unittest.main()

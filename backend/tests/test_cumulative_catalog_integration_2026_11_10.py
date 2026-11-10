"""Cross-branch catalog integration and evidence-safety regression tests."""
import json
import unittest
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
PRODUCTS = CATALOG["products"]
VARIANTS = CATALOG["variants"]


def duplicates(values):
    return sum(1 for count in Counter(values).values() if count > 1)


def product(product_id):
    return next(p for p in PRODUCTS if p.get("product_id") == product_id)


def variants_for(product_id):
    return [v for v in VARIANTS if v.get("product_id") == product_id]


class CumulativeCatalogIntegrationTests(unittest.TestCase):
    def test_global_identity_variant_gtin_and_orphan_integrity(self):
        product_ids = {p.get("product_id") for p in PRODUCTS}
        normalized_names = [
            (p.get("brand", "").casefold(), p.get("canonical_name", "").casefold())
            for p in PRODUCTS
        ]
        tuples = [
            (v.get("product_id"), v.get("size_ml"), v.get("concentration"))
            for v in VARIANTS
        ]
        gtins = [v.get("gtin") for v in VARIANTS if v.get("gtin")]
        self.assertEqual(duplicates([p.get("product_id") for p in PRODUCTS]), 0)
        self.assertEqual(duplicates([v.get("variant_id") for v in VARIANTS]), 0)
        self.assertEqual(duplicates(normalized_names), 0)
        self.assertEqual(duplicates(tuples), 0)
        self.assertEqual(duplicates(gtins), 0)
        self.assertEqual(sum(1 for v in VARIANTS if v.get("product_id") not in product_ids), 0)

    def test_canonical_variants_contain_no_retail_offer_data(self):
        forbidden = {
            "price", "price_amount", "currency", "availability", "stock",
            "in_stock", "offer_url", "retailer", "store_id",
        }
        for variant in VARIANTS:
            with self.subTest(variant=variant.get("variant_id")):
                self.assertFalse(forbidden.intersection(variant))

    def test_four_explicit_gulf_orchid_variants_and_maison_asrar_vanilla_aura(self):
        expected = {
            "SH-GULF-ORCHID-4133b3ae": 100,
            "SH-GULF-ORCHID-EXOTIC-OUD": 100,
            "SH-GULF-ORCHID-VANILLA-LATTE": 100,
            "SH-GULF-ORCHID-COOKIE-BITE": 100,
            "SH-MAISON-ASRAR-bab16c06": 100,
        }
        for product_id, size in expected.items():
            with self.subTest(product=product_id):
                p = product(product_id)
                self.assertEqual(p.get("formats_ml"), [size])
                self.assertEqual(p.get("concentration"), "Eau de Parfum")
                matching = variants_for(product_id)
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("size_ml"), size)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")

    def test_velixir_sacred_four_have_both_extrait_sizes(self):
        expected_ids = {
            "SH-VELIXIR-50b87cfb",
            "SH-VELIXIR-36e7a5ca",
            "SH-VELIXIR-7e147c46",
            "SH-VELIXIR-1738e7af",
        }
        for product_id in expected_ids:
            with self.subTest(product=product_id):
                p = product(product_id)
                self.assertEqual(p.get("formats_ml"), [35, 100])
                rows = variants_for(product_id)
                self.assertEqual({v.get("size_ml") for v in rows}, {35, 100})
                self.assertTrue(all(v.get("concentration") == "Extrait de Parfum" for v in rows))

    def test_ambiguous_attributes_are_not_promoted_to_variants(self):
        for product_id in (
            "SH-GULF-ORCHID-TAHARA-VANILLA-MUSK",
            "SH-MAISON-ASRAR-19d98178",
            "SH-ARABIYAT-PRESTIGE-7bf3b46e",
        ):
            with self.subTest(product=product_id):
                p = product(product_id)
                self.assertNotIn("formats_ml", p)
                self.assertNotIn("concentration", p)
                self.assertEqual(variants_for(product_id), [])

    def test_existing_armaf_intenso_fuego_variant_is_preserved(self):
        rows = variants_for("SH-ARMAF-4c83dfcd")
        self.assertTrue(any(v.get("size_ml") == 105 for v in rows))
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        row = next(p for p in family["products"] if p.get("canonical_name") == "Club de Nuit Intenso Fuego")
        self.assertIn(105, row.get("formats_ml", []))


    def test_four_merged_khadlaj_variants_remain_present_and_registry_aligned(self):
        expected = {
            "SH-KHADLAJ-c0a0f7d9": ("Panache Eleganza", 100, "Extrait de Parfum", "6298043070812"),
            "SH-KHADLAJ-SPRAY-HARVEST-104": ("Oud Noir", 100, "Eau de Parfum", None),
            "SH-KHADLAJ-SPRAY-HARVEST-106": ("Ombre Notes", 100, "Eau de Parfum", None),
            "SH-KHADLAJ-SPRAY-HARVEST-112": ("Infini", 100, "Eau de Parfum", "6297000742625"),
        }
        for product_id, (name, size, concentration, gtin) in expected.items():
            with self.subTest(product=name):
                p = product(product_id)
                self.assertEqual(p.get("canonical_name"), name)
                self.assertEqual(p.get("identity_status"), "source_verified_name")
                self.assertEqual(p.get("formats_ml"), [size])
                self.assertEqual(p.get("concentration"), concentration)
                rows = variants_for(product_id)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("size_ml"), size)
                self.assertEqual(rows[0].get("concentration"), concentration)
                self.assertEqual(rows[0].get("gtin"), gtin)
                family = next(f for f in REGISTRY["families"] if f.get("family_id") == p["family_id"])
                family_rows = [row for row in family["products"] if row.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [size])


    def test_paris_corner_europe_four_explicit_product_variants(self):
        expected = {
            "SH-PARIS-CORNER-cd8b1f8e": ("Bayn Al Asrar", 80, "https://www.pariscornerperfumes.com/products/bayn-al-asrar", "https://de.pariscornereurope.com/en/products/paris-corner-bayn-al-asrar-edp-w-80-ml"),
            "SH-PARIS-CORNER-ef841988": ("December Vanilla", 85, "https://www.pariscornerperfumes.com/products/december-vanilla", "https://de.pariscornereurope.com/en/products/paris-corner-december-vanilla-edp-u-85-ml"),
            "SH-PARIS-CORNER-COCONUT-LAGOON": ("Coconut Lagoon", 100, "https://www.pariscornerperfumes.com/products/coconut-lagoon-100ml", "https://de.pariscornereurope.com/en/products/coconut-lagoon"),
            "SH-PARIS-CORNER-CHERRY-COLA": ("Cherry Cola", 75, "https://www.pariscornerperfumes.com/products/cherry-cola", "https://de.pariscornereurope.com/en/products/cherry-cola-emir"),
        }
        for product_id, (name, size, canonical_url, evidence_url) in expected.items():
            with self.subTest(product=name):
                p = product(product_id)
                self.assertEqual(p.get("canonical_name"), name)
                self.assertEqual(p.get("identity_status"), "source_verified_name")
                self.assertEqual(p.get("source_url"), canonical_url)
                self.assertEqual(p.get("source_evidence_url"), evidence_url)
                self.assertEqual(p.get("formats_ml"), [size])
                self.assertEqual(p.get("concentration"), "Eau de Parfum")
                rows = variants_for(product_id)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("variant_id"), f"SHV-{product_id}-{size}-000")
                self.assertEqual(rows[0].get("size_ml"), size)
                self.assertEqual(rows[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(rows[0].get("source_evidence_url"), evidence_url)
                self.assertNotIn("gtin", rows[0])
                family = next(f for f in REGISTRY["families"] if f.get("family_id") == p["family_id"])
                family_rows = [row for row in family["products"] if row.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [size])

if __name__ == "__main__":
    unittest.main()

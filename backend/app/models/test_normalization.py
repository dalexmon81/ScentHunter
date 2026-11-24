"""Regression tests for canonical fragrance identity normalization."""
import unittest

from app.catalog.normalization import (
    build_identity,
    extract_concentration,
    extract_format_flags,
    extract_size_from_text,
    normalize_brand,
    normalize_fragrance_name,
    normalize_text,
)


class NormalizationTests(unittest.TestCase):
    def test_unicode_and_punctuation(self):
        self.assertEqual(normalize_text("  L’Homme Édition! "), "l homme edition")

    def test_curated_brand_aliases_are_exact(self):
        self.assertEqual(normalize_brand("Christian Dior"), "dior")
        self.assertEqual(normalize_brand("Dior"), "dior")
        self.assertEqual(normalize_brand("Nishane Istanbul"), "nishane")
        self.assertEqual(normalize_brand("Emporio Armani"), "emporio armani")

    def test_concentration_is_explicit_and_distinct(self):
        self.assertEqual(extract_concentration("Sauvage Eau de Parfum"), "edp")
        self.assertEqual(extract_concentration("Sauvage EDT"), "edt")
        self.assertIsNone(extract_concentration("Sauvage"))

    def test_only_ml_size_is_extracted_from_text(self):
        self.assertEqual(extract_size_from_text("Sauvage EDP 100 ml"), 100)
        self.assertIsNone(extract_size_from_text("Sauvage EDP 3.4 oz"))

    def test_sellable_format_is_separate(self):
        flags = extract_format_flags("Sauvage Eau de Parfum Tester")
        self.assertTrue(flags["is_tester"])
        self.assertFalse(flags["is_refill"])
        self.assertFalse(flags["is_gift_set"])
        regular = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml")
        tester = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml Tester")
        self.assertNotEqual(regular.canonical_key, tester.canonical_key)

    def test_concentration_size_and_format_generate_distinct_keys(self):
        edp_100 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml")
        edt_100 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDT 100 ml")
        edp_60 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 60 ml")
        refill = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml Refill")
        self.assertEqual(len({edp_100.canonical_key, edt_100.canonical_key, edp_60.canonical_key, refill.canonical_key}), 4)

    def test_model_numbers_are_not_removed_as_size(self):
        self.assertEqual(normalize_fragrance_name("No. 5 Eau de Parfum 100 ml"), "no 5")
        self.assertEqual(normalize_fragrance_name("212 VIP Eau de Toilette 100 ml"), "212 vip")

    def test_unknown_format_is_not_regular(self):
        known = build_identity(brand="Dior", fragrance_name="Sauvage")
        regular = build_identity(brand="Dior", fragrance_name="Sauvage", is_tester=False, is_refill=False, is_gift_set=False, is_mini=False)
        self.assertNotEqual(known.canonical_key, regular.canonical_key)

    def test_legacy_import_path_remains_compatible(self):
        from app.models.normalization import build_identity as legacy_build_identity
        from app.catalog.normalization import build_identity as catalog_build_identity
        self.assertEqual(
            legacy_build_identity(brand="Dior", fragrance_name="Sauvage").canonical_key,
            catalog_build_identity(brand="Dior", fragrance_name="Sauvage").canonical_key,
        )


if __name__ == "__main__":
    unittest.main()

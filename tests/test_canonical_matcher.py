"""Regression tests for conservative canonical matching and catalog aliases."""
import json
import tempfile
import unittest
from pathlib import Path

from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.scenthunter_next_engine.models import MatchStatus, RetailerOffer
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher, normalize_identity_text


class CanonicalMatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
        json.dump({
            "products": [
                {"product_id": "P-ONE", "brand_name": "Maison Exemple", "canonical_name": "Bois Clair", "aliases": ["Maison Exemple Bois Clair", "Bois Clair Eau de Parfum"]},
                {"product_id": "P-TWO", "brand_name": "Maison Exemple", "canonical_name": "Bois Clair", "aliases": []},
                {"product_id": "P-MULTI", "brand_name": "Autre Maison", "canonical_name": "Nuit Douce", "aliases": ["Nuit Douce"]},
                {"product_id": "P-NOVAR", "brand_name": "Sans Format", "canonical_name": "Sans Variante"},
                {"product_id": "P-UNIQUE", "brand_name": "Maison Unique", "canonical_name": "Aube", "aliases": ["Aube Eau de Parfum"]},
                {"product_id": "P-LIQUID", "brand_name": "French Avenue", "canonical_name": "Liquid Brun Limited Edition", "aliases": ["French Avenue Liquid Brun Limited Edition", "Liquid Brun Limited Edition 150ml", "Liquid Brun Limited Edition Extrait de Parfum"]},
                {"product_id": "P-LIQUID-BASE", "brand_name": "French Avenue", "canonical_name": "Liquid Brun", "aliases": ["Liquid Brun 100 ML"]}
            ],
            "variants": [
                {"variant_id": "V-100", "product_id": "P-ONE", "size_ml": 100},
                {"variant_id": "V-50", "product_id": "P-TWO", "size_ml": 50},
                {"variant_id": "V-N-30", "product_id": "P-MULTI", "size_ml": 30, "aliases": ["Nuit Douce 30 ml"]},
                {"variant_id": "V-N-75", "product_id": "P-MULTI", "size_ml": 75, "aliases": ["Nuit Douce 75 ml"]},
                {"variant_id": "V-AUBE-100", "product_id": "P-UNIQUE", "size_ml": 100},
                {"variant_id": "V-LIQUID-150", "product_id": "P-LIQUID", "size_ml": 150, "aliases": ["Liquid Brun Limited Edition Extrait de Parfum", "Liquid Brun Limited Edition 150ml"]},
                {"variant_id": "V-LIQUID-100", "product_id": "P-LIQUID-BASE", "size_ml": 100, "aliases": ["Liquid Brun 100 ML"]}
            ]
        }, self.tmp)
        self.tmp.close()
        self.addCleanup(lambda: Path(self.tmp.name).unlink(missing_ok=True))
        self.matcher = CanonicalMatcher(CatalogRepository.from_file(self.tmp.name))

    def offer(self, name, brand=None, size=None):
        return RetailerOffer(retailer="Test Shop", raw_name=name, brand_raw=brand, size_ml=size)

    def test_normalizes_accents_and_punctuation(self):
        self.assertEqual(normalize_identity_text("Été & Nuit!"), "ete and nuit")

    def test_duplicate_canonical_names_remain_ambiguous(self):
        result = self.matcher.match(self.offer("Bois Clair", "Maison Exemple", 100))
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)
        self.assertEqual(set(result.candidate_product_ids), {"P-ONE", "P-TWO"})

    def test_unique_name_brand_and_size_match_real_ids(self):
        result = self.matcher.match(self.offer("Aube", "Maison Unique", 100))
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-UNIQUE")
        self.assertEqual(result.canonical_variant_id, "V-AUBE-100")

    def test_generic_concentration_suffix_is_tolerated(self):
        result = self.matcher.match(self.offer("Aube Eau de Parfum", "Maison Unique", 100))
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_variant_id, "V-AUBE-100")

    def test_name_match_without_brand_is_ambiguous_when_multiple_products_exist(self):
        result = self.matcher.match(self.offer("Bois Clair", size=100))
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)

    def test_multi_variant_product_without_size_stays_unresolved(self):
        result = self.matcher.match(self.offer("Nuit Douce", "Autre Maison"))
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "format_missing_for_multi_variant_product")

    def test_explicit_size_without_canonical_variant_stays_unresolved(self):
        result = self.matcher.match(self.offer("Nuit Douce", "Autre Maison", 100))
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "explicit_size_has_no_canonical_variant")

    def test_no_fuzzy_name_match(self):
        result = self.matcher.match(self.offer("Bois Clair Extra", "Maison Exemple", 100))
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)

    def test_product_without_variants_stays_unresolved(self):
        result = self.matcher.match(self.offer("Sans Variante", "Sans Format"))
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "canonical_product_has_no_declared_variants")

    def test_product_alias_matches_without_fuzzy_logic(self):
        result = self.matcher.match(self.offer("Bois Clair Eau de Parfum", "Maison Exemple", 100))
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)

    def test_variant_alias_resolves_format_when_size_field_missing(self):
        result = self.matcher.match(self.offer("Nuit Douce 75 ml", "Autre Maison"))
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_variant_id, "V-N-75")

    def test_explicit_size_conflicting_with_variant_alias_fails_closed(self):
        result = self.matcher.match(self.offer("Nuit Douce 75 ml", "Autre Maison", 30))
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "matched_variant_alias_conflicts_with_explicit_size")

    def test_liquid_brun_limited_edition_alias_matches_canonical_variant(self):
        result = self.matcher.match(self.offer(
            "Liquid Brun Limited Edition Extrait De Parfum", "FRENCH AVENUE", 150
        ))
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-LIQUID")
        self.assertEqual(result.canonical_variant_id, "V-LIQUID-150")

    def test_liquid_brun_100_ml_alias_matches_canonical_variant(self):
        result = self.matcher.match(self.offer("Liquid Brun 100 ML", "FRENCH AVENUE", 100))
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-LIQUID-BASE")
        self.assertEqual(result.canonical_variant_id, "V-LIQUID-100")


if __name__ == "__main__":
    unittest.main()

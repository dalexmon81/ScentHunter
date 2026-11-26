from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.models import MatchStatus, RetailerOffer


class CanonicalMatcherConcentrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.temp_dir.name) / "product_catalog.json"
        self.catalog_path.write_text(
            json.dumps({
                "products": [{
                    "product_id": "SH-0030",
                    "brand_name": "French Avenue",
                    "canonical_name": "Liquid Brun",
                    "aliases": ["French Avenue Liquid Brun", "Liquid Brun"],
                    "concentration": "Eau de Parfum",
                }],
                "variants": [{
                    "product_id": "SH-0030",
                    "variant_id": "VAR-f87146c82d167f4c",
                    "size_ml": 100,
                    "aliases": ["Liquid Brun Eau de Parfum 100 ML"],
                }],
            }),
            encoding="utf-8",
        )
        self.matcher = CanonicalMatcher(
            CatalogRepository.from_file(self.catalog_path)
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_edp_abbreviation_matches_exact_canonical_variant(self) -> None:
        offer = RetailerOffer(
            retailer="notino",
            raw_name="Liquid Brun EDP 100ml",
            brand_raw="French Avenue",
            size_ml=100,
        )
        result = self.matcher.match(offer)
        self.assertIs(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "SH-0030")
        self.assertEqual(
            result.canonical_variant_id, "VAR-f87146c82d167f4c"
        )

    def test_notino_french_gender_suffix_matches_exact_canonical_variant(self) -> None:
        offer = RetailerOffer(
            retailer="notino-fr",
            raw_name="French Avenue Liquid Brun Eau de Parfum pour homme 100 ml",
            brand_raw="French Avenue",
            size_ml=100,
        )
        result = self.matcher.match(offer)
        self.assertIs(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "SH-0030")
        self.assertEqual(
            result.canonical_variant_id, "VAR-f87146c82d167f4c"
        )

    def test_shopify_brand_attribution_matches_exact_canonical_variant(self) -> None:
        offer = RetailerOffer(
            retailer="orioudh",
            raw_name="Liquid Brun by French Avenue - Men Perfume - EDP - 100 ml",
            brand_raw="French Avenue",
            size_ml=100,
        )
        result = self.matcher.match(offer)
        self.assertIs(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "SH-0030")
        self.assertEqual(
            result.canonical_variant_id, "VAR-f87146c82d167f4c"
        )

    def test_conflicting_edt_is_not_promoted_as_edp(self) -> None:
        offer = RetailerOffer(
            retailer="notino",
            raw_name="Liquid Brun EDT 100ml",
            brand_raw="French Avenue",
            size_ml=100,
        )
        result = self.matcher.match(offer)
        self.assertIs(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "canonical_concentration_conflict")


if __name__ == "__main__":
    unittest.main()

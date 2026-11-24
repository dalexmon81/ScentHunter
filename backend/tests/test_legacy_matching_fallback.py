from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.matching.legacy_fallback import build_legacy_matcher, resolve_legacy_catalog_match


class FakeLegacyMatcher:
    def __init__(self, aggregation):
        self.aggregation = aggregation
        self.calls = []

    def process_offers(self, offers):
        self.calls.append(offers)
        return self.aggregation


class LegacyMatchingFallbackTests(unittest.TestCase):
    def test_builds_legacy_matcher_only_from_existing_catalog_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "product_catalog.json"
            catalog.write_text("{}", encoding="utf-8")
            matcher = object()
            with patch(
                "scenthunter_next_engine.next_engine_service.NextEngineService.from_catalog_file",
                return_value=matcher,
            ) as factory:
                result = build_legacy_matcher(catalog)
        self.assertIs(result, matcher)
        factory.assert_called_once_with(catalog)

    def test_missing_legacy_catalog_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            with self.assertRaisesRegex(RuntimeError, "catalog is missing"):
                build_legacy_matcher(missing)

    def test_returns_only_one_unambiguous_legacy_candidate(self):
        group = SimpleNamespace(
            canonical_product_id="legacy-product-1",
            canonical_variant_id="legacy-variant-1",
            offers=[object()],
        )
        aggregation = SimpleNamespace(
            input_count=1, matched_offer_count=1, groups=[group],
            unresolved=[], ambiguous=[],
        )
        matcher = FakeLegacyMatcher(aggregation)
        offer = object()
        result = resolve_legacy_catalog_match(matcher, offer)
        self.assertEqual(result.legacy_product_id, "legacy-product-1")
        self.assertEqual(result.legacy_variant_id, "legacy-variant-1")
        self.assertIsNone(result.reason)
        self.assertEqual(matcher.calls, [[offer]])

    def test_rejects_ambiguous_or_non_single_match(self):
        unresolved = SimpleNamespace(reason="incomplete_identity", status=SimpleNamespace(value="unmatched"))
        ambiguous = SimpleNamespace(reason="two_variants", status=SimpleNamespace(value="ambiguous"))
        aggregation = SimpleNamespace(
            input_count=1, matched_offer_count=0, groups=[],
            unresolved=[unresolved], ambiguous=[ambiguous],
        )
        result = resolve_legacy_catalog_match(FakeLegacyMatcher(aggregation), object())
        self.assertIsNone(result.legacy_product_id)
        self.assertIsNone(result.legacy_variant_id)
        self.assertEqual(result.reason, "incomplete_identity;two_variants")

    def test_empty_aggregation_returns_stable_review_reason(self):
        aggregation = SimpleNamespace(
            input_count=1, matched_offer_count=0, groups=[],
            unresolved=[], ambiguous=[],
        )
        result = resolve_legacy_catalog_match(FakeLegacyMatcher(aggregation), object())
        self.assertEqual(result.reason, "no_single_canonical_variant_match")


if __name__ == "__main__":
    unittest.main()

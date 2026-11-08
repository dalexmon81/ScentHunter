from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from scripts.audit_variant_coverage import build_report


def test_variant_coverage_requires_size_and_concentration_but_not_gtin():
    rows = [
        {
            "brand_name": "French Avenue",
            "fragrance_name": "Liquid Brun",
            "variant_count": 1,
            "variants_with_size": 1,
            "variants_with_concentration": 1,
            "variants_with_gtin": 1,
            "complete_variant_count": 1,
        },
        {
            "brand_name": "French Avenue",
            "fragrance_name": "Vulcan Feu",
            "variant_count": 1,
            "variants_with_size": 1,
            "variants_with_concentration": 1,
            "variants_with_gtin": 0,
            "complete_variant_count": 1,
        },
        {
            "brand_name": "Lattafa",
            "fragrance_name": "Khamrah",
            "variant_count": 1,
            "variants_with_size": 1,
            "variants_with_concentration": 0,
            "variants_with_gtin": 0,
            "complete_variant_count": 0,
        },
        {
            "brand_name": "Lattafa",
            "fragrance_name": "Yara",
            "variant_count": 0,
            "variants_with_size": 0,
            "variants_with_concentration": 0,
            "variants_with_gtin": 0,
            "complete_variant_count": 0,
        },
    ]

    report = build_report(rows)

    assert report["fragrances"] == 4
    assert report["fragrances_with_variants"] == 3
    assert report["fragrances_without_variants"] == 1
    assert report["fragrances_with_at_least_one_complete_variant"] == 2
    assert report["fragrances_needing_variant_research"] == 2
    assert report["fragrance_coverage_percent"] == 75.0
    assert report["variant_completeness_percent"] == 66.67
    assert report["variant_rows"] == 3
    assert report["complete_variant_rows"] == 2
    assert report["variant_rows_needing_research"] == 1
    assert report["variants_with_gtin"] == 1
    assert report["gtin_coverage_percent"] == 33.33
    assert report["incomplete_variant_research"] == [
        {
            "brand": "Lattafa",
            "fragrance": "Khamrah",
            "variant_count": 1,
            "complete_variant_count": 0,
            "variants_needing_research": 1,
            "variants_missing_size": 0,
            "variants_missing_concentration": 1,
            "variants_missing_gtin": 1,
        },
        {
            "brand": "Lattafa",
            "fragrance": "Yara",
            "variant_count": 0,
            "complete_variant_count": 0,
            "variants_needing_research": 0,
            "variants_missing_size": 0,
            "variants_missing_concentration": 0,
            "variants_missing_gtin": 0,
        },
    ]
    assert report["variants_created"] == 0
    assert report["retailer_requests_made"] == 0
    assert report["database_modified"] is False


def test_empty_variant_coverage_report_is_safe():
    report = build_report([])
    assert report["fragrances"] == 0
    assert report["fragrance_coverage_percent"] == 0.0
    assert report["variant_completeness_percent"] == 0.0
    assert report["gtin_coverage_percent"] == 0.0
    assert report["incomplete_variant_research"] == []



def test_variant_research_queue_includes_incomplete_sibling_even_if_one_variant_is_complete():
    report = build_report([
        {
            "brand_name": "Armaf",
            "fragrance_name": "Club de Nuit",
            "variant_count": 2,
            "variants_with_size": 2,
            "variants_with_concentration": 1,
            "variants_with_gtin": 1,
            "complete_variant_count": 1,
        }
    ])

    assert report["fragrances_with_at_least_one_complete_variant"] == 1
    assert report["fragrances_needing_variant_research"] == 1
    assert report["variant_rows_needing_research"] == 1
    assert report["variant_completeness_percent"] == 50.0
    assert report["incomplete_variant_research"] == [
        {
            "brand": "Armaf",
            "fragrance": "Club de Nuit",
            "variant_count": 2,
            "complete_variant_count": 1,
            "variants_needing_research": 1,
            "variants_missing_size": 0,
            "variants_missing_concentration": 1,
            "variants_missing_gtin": 1,
        }
    ]

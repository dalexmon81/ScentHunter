from scripts.audit_variant_coverage import build_report


def test_variant_coverage_report_counts_missing_variants_without_inventing_them():
    report = build_report([
        {"brand_name": "Armaf", "fragrance_name": "Club de Nuit", "variant_count": 2},
        {"brand_name": "Armaf", "fragrance_name": "Untold", "variant_count": 0},
        {"brand_name": "Khadlaj", "fragrance_name": "Island", "variant_count": 1},
    ])

    assert report["fragrances"] == 3
    assert report["fragrances_with_variants"] == 2
    assert report["fragrances_without_variants"] == 1
    assert report["variant_rows"] == 3
    assert report["coverage_percent"] == 66.67
    assert report["missing_variant_research"] == [
        {"brand": "Armaf", "fragrance": "Untold"}
    ]
    assert report["variants_created"] == 0
    assert report["retailer_requests_made"] == 0
    assert report["database_modified"] is False


def test_empty_catalog_has_zero_coverage_not_division_error():
    report = build_report([])
    assert report["fragrances"] == 0
    assert report["coverage_percent"] == 0.0

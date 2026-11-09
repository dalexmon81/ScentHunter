"""Regression tests for cross-PR catalog identity normalization."""
from backend.scripts.audit_cross_pr_catalogs import product_identity


def test_trailing_bottle_volume_does_not_create_a_second_product_identity():
    regular = {"brand": "Gulf Orchid", "canonical_name": "Sweet Heaven Extreme"}
    mini = {"brand": "Gulf Orchid", "canonical_name": "Sweet Heaven Extreme 20ml"}
    assert product_identity(regular) == product_identity(mini)


def test_volume_is_removed_only_from_the_trailing_product_name_suffix():
    row = {"brand": "Example", "canonical_name": "No. 20 Eau de Parfum 100 ml"}
    assert product_identity(row)[1] == "no20eaudeparfum"


def test_latest_catalog_prs_are_included_in_cross_pr_audit():
    from backend.scripts.audit_cross_pr_catalogs import CANDIDATE_PRS

    candidate_numbers = {number for number, _head, _base in CANDIDATE_PRS}
    assert {562, 565, 599, 603, 604}.issubset(candidate_numbers)
    assert 578 not in candidate_numbers
    assert 600 not in candidate_numbers

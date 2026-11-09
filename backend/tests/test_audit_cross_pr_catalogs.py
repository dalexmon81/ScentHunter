"""Regression tests for cross-PR catalog identity normalization."""
from backend.scripts.audit_cross_pr_catalogs import product_identity


def test_trailing_bottle_volume_does_not_create_a_second_product_identity():
    regular = {"brand": "Gulf Orchid", "canonical_name": "Sweet Heaven Extreme"}
    mini = {"brand": "Gulf Orchid", "canonical_name": "Sweet Heaven Extreme 20ml"}
    assert product_identity(regular) == product_identity(mini)


def test_volume_is_removed_only_from_the_trailing_product_name_suffix():
    row = {"brand": "Example", "canonical_name": "No. 20 Eau de Parfum 100 ml"}
    assert product_identity(row)[1] == "no20eaudeparfum"

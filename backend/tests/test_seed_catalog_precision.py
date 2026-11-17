from decimal import Decimal

import pytest

from scripts.seed_catalog import _parse_size_ml, validate_catalog


def test_seed_size_parser_preserves_fractional_precision():
    assert _parse_size_ml("50.5") == Decimal("50.5")
    assert _parse_size_ml("50.5000") == Decimal("50.5000")
    assert _parse_size_ml("100") == Decimal("100")
    assert _parse_size_ml(None) is None


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "50.12345", "1000000"])
def test_seed_size_parser_rejects_invalid_or_unrepresentable_sizes(value):
    with pytest.raises(ValueError):
        _parse_size_ml(value)


def test_catalog_validation_accepts_fractional_variant_sizes():
    products = [{
        "product_id": "fractional-product",
        "brand_name": "Test Brand",
        "canonical_name": "Fractional Test",
    }]
    variants = [{
        "variant_id": "fractional-variant",
        "product_id": "fractional-product",
        "size_ml": "50.5",
    }]
    checked_products, by_product, blocked = validate_catalog({
        "products": products,
        "variants": variants,
    })
    assert checked_products == products
    assert by_product["fractional-product"] == variants
    assert blocked == []


def test_catalog_validation_rejects_sizes_beyond_numeric_scale():
    products = [{
        "product_id": "fractional-product",
        "brand_name": "Test Brand",
        "canonical_name": "Fractional Test",
    }]
    variants = [{
        "variant_id": "fractional-variant",
        "product_id": "fractional-product",
        "size_ml": "50.12345",
    }]
    _products, _by_product, blocked = validate_catalog({
        "products": products,
        "variants": variants,
    })
    assert blocked == ["fractional-variant: invalid size_ml '50.12345'"]

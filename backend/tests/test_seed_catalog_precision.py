from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import pytest

from app.models import Base, Store
from scripts.seed_catalog import _collect_variant_identifiers, _parse_size_ml, ensure_bplatz_store, validate_catalog


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



def test_bplatz_seed_preserves_existing_operator_ttl_and_fills_missing_value():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            store = Store(
                name="Bplatz old", slug="bplatz", domain="old.example",
                country="DE", currency="EUR", status="active",
                offer_ttl_minutes=75,
            )
            session.add(store)
            session.flush()

            seeded = ensure_bplatz_store(session)
            assert seeded.id == store.id
            assert seeded.domain == "bplatz.de"
            assert seeded.offer_ttl_minutes == 75

            seeded.offer_ttl_minutes = None
            session.flush()
            seeded_again = ensure_bplatz_store(session)
            assert seeded_again.offer_ttl_minutes == 1440
    finally:
        engine.dispose()



def test_variant_identifier_collection_preserves_gtin_mpn_and_store_sku_namespaces():
    product = {"brand_name": "Lancôme"}
    variant = {
        "variant_id": "variant-1",
        "gtins": ["4006381333931"],
        "mpns": ["abc-123"],
        "store_mappings": [{
            "store": "Deloox",
            "sku": "sku-009",
            "url": "https://www.deloox.com/product/sku-009",
        }],
    }

    identifiers = _collect_variant_identifiers(product, variant)
    by_type = {item["identifier_type"]: item for item in identifiers}

    assert by_type["gtin"]["namespace"] == "global"
    assert by_type["gtin"]["normalized_value"] == "4006381333931"
    assert by_type["mpn"]["namespace"] == "brand:lancome"
    assert by_type["mpn"]["normalized_value"] == "ABC-123"
    assert by_type["sku"]["namespace"] == "store:deloox"
    assert by_type["sku"]["normalized_value"] == "SKU-009"
    assert by_type["sku"]["source_url"] == "https://www.deloox.com/product/sku-009"


def test_variant_identifier_collection_deduplicates_same_normalized_identifier():
    identifiers = _collect_variant_identifiers(
        {"brand_name": "Test"},
        {"gtins": ["4006381333931", "4006-3813-33931"]},
    )
    assert len(identifiers) == 1


@pytest.mark.parametrize("value", ["123", "ABCDEFGHIJKLM", "4006381333931X"])
def test_variant_identifier_collection_rejects_invalid_gtin(value):
    with pytest.raises(ValueError, match="invalid GTIN"):
        _collect_variant_identifiers({"brand_name": "Test"}, {"gtins": [value]})


def test_catalog_validation_rejects_identifier_collision_across_variants():
    products = [{
        "product_id": "product-1",
        "brand_name": "Test Brand",
        "canonical_name": "Test Fragrance",
    }]
    variants = [
        {"variant_id": "variant-1", "product_id": "product-1", "size_ml": "50", "gtins": ["4006381333931"]},
        {"variant_id": "variant-2", "product_id": "product-1", "size_ml": "100", "gtins": ["4006381333931"]},
    ]
    _products, _by_product, blocked = validate_catalog({
        "products": products,
        "variants": variants,
    })
    assert any("already assigned to variant-1" in item for item in blocked)

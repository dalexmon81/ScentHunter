from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance, ProductVariant
from app.services.canonical_identity_persistence import plan_canonical_identity
from app.services.product_normalization import normalize_product


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def _seed(session, *, gtin=None):
    brand = Brand(name="Christian Dior", slug="christian-dior",
                  normalized_name="christian dior")
    session.add(brand)
    session.flush()
    fragrance = Fragrance(brand_id=brand.id, name="sauvage", slug="sauvage")
    session.add(fragrance)
    session.flush()
    variant = ProductVariant(
        fragrance_id=fragrance.id, concentration="edp", size_ml=100,
        is_tester=False, is_refill=False, is_gift_set=False, is_mini=False,
        gtin=gtin,
        canonical_key="christian-dior|sauvage|edp|100|standard",
    )
    session.add(variant)
    session.commit()
    return brand, fragrance, variant


def test_dry_run_plans_missing_brand_without_writing():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        plan = plan_canonical_identity(session, product)
        assert plan.status == "create_brand"
        assert session.scalar(select(Brand.id)) is None
        assert session.scalar(select(Fragrance.id)) is None
        assert session.scalar(select(ProductVariant.id)) is None
    finally:
        session.close()
        engine.dispose()


def test_existing_identity_is_resolved_without_mutation():
    engine, session = _session()
    try:
        _brand, _fragrance, variant = _seed(session, gtin="4006381333931")
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        plan = plan_canonical_identity(session, product, gtin="4006381333931")
        assert plan.status == "existing"
        assert plan.product_variant_id == variant.id
        assert session.get(ProductVariant, variant.id).is_mini is False
    finally:
        session.close()
        engine.dispose()


def test_brand_slug_collision_is_sent_to_review():
    engine, session = _session()
    try:
        session.add(Brand(name="Other Brand", slug="christian-dior",
                          normalized_name="other brand"))
        session.commit()
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        plan = plan_canonical_identity(session, product)
        assert plan.status == "review"
        assert plan.reason == "brand_slug_collision_requires_review"
    finally:
        session.close()
        engine.dispose()


def test_same_canonical_key_with_different_valid_gtin_requires_review():
    engine, session = _session()
    try:
        _seed(session, gtin="4006381333931")
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        plan = plan_canonical_identity(session, product, gtin="5901234123457")
        assert plan.status == "review"
        assert plan.reason == "different_valid_gtin_requires_review"
    finally:
        session.close()
        engine.dispose()


def test_same_canonical_key_with_missing_gtin_is_not_auto_accepted():
    engine, session = _session()
    try:
        _seed(session, gtin="4006381333931")
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        plan = plan_canonical_identity(session, product)
        assert plan.status == "review"
        assert plan.reason == "incomplete_gtin_identity_requires_review"
    finally:
        session.close()
        engine.dispose()

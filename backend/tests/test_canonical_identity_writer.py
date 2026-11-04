from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance, ProductVariant
from app.services.canonical_identity_writer import persist_canonical_identity
from app.services.product_normalization import normalize_product


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def test_writer_is_blocked_without_explicit_opt_in():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        result = persist_canonical_identity(session, product)
        assert result.status == "blocked"
        assert result.reason == "explicit_create_opt_in_required"
        assert session.scalar(select(func.count()).select_from(Brand)) == 0
        assert session.scalar(select(func.count()).select_from(Fragrance)) == 0
        assert session.scalar(select(func.count()).select_from(ProductVariant)) == 0
    finally:
        session.close()
        engine.dispose()


def test_writer_inserts_missing_identity_but_does_not_commit():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        result = persist_canonical_identity(
            session, product, gtin="4006381333931", allow_create=True
        )
        assert result.status == "created"
        assert result.brand_id is not None
        assert result.fragrance_id is not None
        assert result.product_variant_id is not None
        assert session.scalar(select(func.count()).select_from(Brand)) == 1
        assert session.scalar(select(func.count()).select_from(Fragrance)) == 1
        variant = session.get(ProductVariant, result.product_variant_id)
        assert variant is not None
        assert variant.canonical_key == product.canonical_key
        assert variant.gtin == "4006381333931"
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Brand)) == 0
        assert session.scalar(select(func.count()).select_from(Fragrance)) == 0
        assert session.scalar(select(func.count()).select_from(ProductVariant)) == 0
    finally:
        session.close()
        engine.dispose()


def test_writer_does_not_change_existing_identity():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        created = persist_canonical_identity(session, product, allow_create=True)
        session.commit()
        again = persist_canonical_identity(session, product, allow_create=True)
        assert again.status == "existing"
        assert again.product_variant_id == created.product_variant_id
        assert session.scalar(select(func.count()).select_from(ProductVariant)) == 1
    finally:
        session.close()
        engine.dispose()


def test_writer_routes_invalid_supplied_gtin_to_review():
    engine, session = _session()
    try:
        product = normalize_product("Dior", "Sauvage EDP 100 ml")
        result = persist_canonical_identity(
            session, product, gtin="4006381333932", allow_create=True
        )
        assert result.status == "review"
        assert result.reason == "invalid_gtin_requires_review"
        assert session.scalar(select(func.count()).select_from(Brand)) == 0
    finally:
        session.close()
        engine.dispose()

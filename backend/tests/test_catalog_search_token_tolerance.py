"""Regression coverage for incidental words in canonical product searches."""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance, ProductVariant
from app.search.catalog import search_catalog


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    brand = Brand(name="Dior", slug="dior", normalized_name="dior")
    session.add(brand)
    session.flush()
    fragrance = Fragrance(
        brand_id=brand.id, name="Sauvage", slug="sauvage",
        image_url=None,
    )
    session.add(fragrance)
    session.flush()
    session.add(ProductVariant(
        fragrance_id=fragrance.id, concentration="Eau de Parfum",
        size_ml=100, is_tester=False, is_refill=False,
        is_gift_set=False, is_mini=False,
        canonical_key="dior|sauvage|edp|100|regular|standard|single|standard",
    ))
    session.commit()
    return engine, session


def test_incidental_spray_word_does_not_hide_known_canonical_product():
    engine, session = _session()
    try:
        exact = search_catalog(session, "Dior Sauvage EDP 100 ml")
        incidental = search_catalog(session, "Dior Sauvage EDP 100 ml spray vaporisateur")
        assert exact["count"] == 1
        assert incidental["count"] == 1
        assert incidental["results"][0]["catalog_id"] == exact["results"][0]["catalog_id"]
    finally:
        session.close()
        engine.dispose()


def test_variant_attributes_remain_strict_filters():
    engine, session = _session()
    try:
        assert search_catalog(session, "Dior Sauvage EDP 50 ml")["count"] == 0
        assert search_catalog(session, "Dior Sauvage EDT 100 ml")["count"] == 0
        assert search_catalog(session, "Dior Sauvage EDP 100 ml tester")["count"] == 0
    finally:
        session.close()
        engine.dispose()

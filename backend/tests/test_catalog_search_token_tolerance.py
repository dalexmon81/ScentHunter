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


def test_canonical_identity_without_variant_remains_searchable_without_offers():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        brand = Brand(name="Rasasi", slug="rasasi", normalized_name="rasasi")
        session.add(brand)
        session.flush()
        session.add(Fragrance(
            brand_id=brand.id, name="Hawas Atlantis", slug="hawas-atlantis",
            image_url=None,
        ))
        session.commit()

        result = search_catalog(session, "Rasasi Hawas")
        assert result["count"] == 1
        assert result["offer_count"] == 0
        assert result["results"][0]["brand"] == "Rasasi"
        assert result["results"][0]["name"] == "Hawas Atlantis Identità catalogo"
        assert result["results"][0]["offers"] == []
        assert result["results"][0]["variant_id"] is None
    finally:
        session.close()
        engine.dispose()



def test_search_groups_sizes_inside_each_fragrance_concentration():
    engine, session = _session()
    try:
        fragrance = session.query(Fragrance).filter_by(name="Sauvage").one()
        session.add_all([
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Toilette",
                size_ml=30, is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edt|30|regular|standard|single|standard",
            ),
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Toilette",
                size_ml=60, is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edt|60|regular|standard|single|standard",
            ),
        ])
        session.commit()

        result = search_catalog(session, "Dior Sauvage")
        assert result["count"] == 2
        edt = next(item for item in result["results"] if "Toilette" in item["name"])
        edp = next(item for item in result["results"] if "Parfum" in item["name"])

        assert [item["size_ml"] for item in edt["formats"]] == [30, 60]
        assert len(edt["variant_ids"]) == 2
        assert [item["size_ml"] for item in edp["formats"]] == [100]
        assert all(" ml" not in item["name"] for item in result["results"])
    finally:
        session.close()
        engine.dispose()


def test_search_does_not_merge_edp_edt_or_tester_packaging():
    engine, session = _session()
    try:
        fragrance = session.query(Fragrance).filter_by(name="Sauvage").one()
        session.add_all([
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Toilette",
                size_ml=30, is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edt|30|regular|standard|single|standard",
            ),
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Toilette",
                size_ml=60, is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edt|60|regular|standard|single|standard",
            ),
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Parfum",
                size_ml=50, is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edp|50|regular|standard|single|standard",
            ),
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Parfum",
                size_ml=100, is_tester=True, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edp|100|tester|standard|single|standard",
            ),
        ])
        session.commit()

        persisted = session.query(ProductVariant).order_by(
            ProductVariant.size_ml, ProductVariant.is_tester
        ).all()
        assert [(item.size_ml, item.concentration, item.is_tester) for item in persisted] == [
            (30, "Eau de Toilette", False),
            (50, "Eau de Parfum", False),
            (60, "Eau de Toilette", False),
            (100, "Eau de Parfum", False),
            (100, "Eau de Parfum", True),
        ]
        result = search_catalog(session, "Dior Sauvage")
        assert result["count"] == 3, result["results"]
        edp = next(item for item in result["results"] if "Eau de Parfum" in item["name"] and "Tester" not in item["name"])
        edt = next(item for item in result["results"] if "Eau de Toilette" in item["name"])
        tester = next(item for item in result["results"] if "Tester" in item["name"])
        assert [item["size_ml"] for item in edp["formats"]] == [50, 100]
        assert [item["size_ml"] for item in edt["formats"]] == [30, 60]
        assert [item["size_ml"] for item in tester["formats"]] == [100]
    finally:
        session.close()
        engine.dispose()

"""Regression coverage for incidental words and verified public search."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Base, Brand, Fragrance, IngestionRaw, MatchAudit, Offer,
    ProductVariant, Store,
)
from app.search.catalog import search_catalog


def _add_verified_offer(session: Session, store: Store, variant: ProductVariant, price: str) -> None:
    """Create a complete, current, explicitly-priced offer accepted by the public gate."""
    raw = IngestionRaw(
        store_id=store.id,
        raw_payload={"currency_explicit": True},
        status="promoted",
        product_variant_id=variant.id,
    )
    session.add(raw)
    session.flush()

    offer = Offer(
        ingestion_raw_id=raw.id,
        store_id=store.id,
        product_variant_id=variant.id,
        external_product_id=f"test-{variant.id}",
        url=f"https://shop.test/item/{variant.id}",
        price=Decimal(price),
        currency="EUR",
        availability="in_stock",
        source="verified-search-test",
        captured_at=datetime.now(timezone.utc),
        status="active",
    )
    session.add(offer)
    session.flush()
    session.add(MatchAudit(
        offer_id=offer.id,
        product_variant_id=variant.id,
        method="test_exact",
        confidence=Decimal("1.000"),
    ))
    session.flush()


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    brand = Brand(name="Dior", slug="dior", normalized_name="dior")
    store = Store(
        name="Verified Test Shop", slug="verified-test-shop",
        domain="shop.test", currency="EUR", status="active",
    )
    session.add_all([brand, store])
    session.flush()
    fragrance = Fragrance(
        brand_id=brand.id, name="Sauvage", slug="sauvage",
        image_url=None,
    )
    session.add(fragrance)
    session.flush()
    variant = ProductVariant(
        fragrance_id=fragrance.id, concentration="Eau de Parfum",
        size_ml=100, is_tester=False, is_refill=False,
        is_gift_set=False, is_mini=False,
        canonical_key="dior|sauvage|edp|100|regular|standard|single|standard",
    )
    session.add(variant)
    session.flush()
    _add_verified_offer(session, store, variant, "99.90")
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


def test_canonical_identity_without_variant_is_retained_but_not_published_without_offers():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        brand = Brand(name="Rasasi", slug="rasasi", normalized_name="rasasi")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(
            brand_id=brand.id, name="Hawas Atlantis", slug="hawas-atlantis",
            image_url=None,
        )
        session.add(fragrance)
        session.commit()

        result = search_catalog(session, "Rasasi Hawas")
        assert session.scalar(select(Fragrance.id).where(Fragrance.id == fragrance.id)) == fragrance.id
        assert result["count"] == 0
        assert result["offer_count"] == 0
        assert result["results"] == []
    finally:
        session.close()
        engine.dispose()


def test_search_groups_sizes_inside_each_fragrance_concentration():
    engine, session = _session()
    try:
        fragrance = session.query(Fragrance).filter_by(name="Sauvage").one()
        store = session.query(Store).filter_by(slug="verified-test-shop").one()
        variants = [
            ProductVariant(
                fragrance_id=fragrance.id, concentration="Eau de Toilette",
                size_ml=size, is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key=f"dior|sauvage|edt|{size}|regular|standard|single|standard",
            )
            for size in (30, 60)
        ]
        session.add_all(variants)
        session.flush()
        for variant, price in zip(variants, ("59.90", "79.90")):
            _add_verified_offer(session, store, variant, price)
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
        store = session.query(Store).filter_by(slug="verified-test-shop").one()
        variants = [
            ProductVariant(
                fragrance_id=fragrance.id, concentration=concentration,
                size_ml=size, is_tester=tester, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key=key,
            )
            for concentration, size, tester, key in [
                ("Eau de Toilette", 30, False, "dior|sauvage|edt|30|regular|standard|single|standard"),
                ("Eau de Toilette", 60, False, "dior|sauvage|edt|60|regular|standard|single|standard"),
                ("Eau de Parfum", 50, False, "dior|sauvage|edp|50|regular|standard|single|standard"),
                ("Eau de Parfum", 100, True, "dior|sauvage|edp|100|tester|standard|single|standard"),
            ]
        ]
        session.add_all(variants)
        session.flush()
        for index, variant in enumerate(variants):
            _add_verified_offer(session, store, variant, f"{49 + index * 10}.90")
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

 

def test_notino_offer_with_stale_feed_timestamp_is_not_published():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        brand = Brand(name="Dior", slug="dior", normalized_name="dior")
        store = Store(name="Notino", slug="notino-fr", domain="notino.fr", currency="EUR", status="active")
        session.add_all([brand, store])
        session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug="sauvage", image_url=None)
        session.add(fragrance)
        session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="Eau de Parfum", size_ml=200,
            is_tester=False, is_refill=False, is_gift_set=False, is_mini=False,
            canonical_key="dior|sauvage|edp|200|regular|standard|single|standard",
        )
        session.add(variant)
        session.flush()
        source_time = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
        raw = IngestionRaw(
            store_id=store.id,
            raw_payload={"currency_explicit": True, "refresh_observation": {"raw_xml": f"<entry><last_updated>{source_time}</last_updated></entry>"}},
            status="promoted", product_variant_id=variant.id,
        )
        session.add(raw)
        session.flush()
        offer = Offer(
            ingestion_raw_id=raw.id, store_id=store.id, product_variant_id=variant.id,
            external_product_id="CHDSVGM_AEDP25", url="https://www.notino.fr/dior/sauvage-eau-de-parfum-pour-homme/p-15971107/",
            price=Decimal("198.00"), currency="EUR", availability="in_stock",
            source="authorized_cj_viv_xml_feed", captured_at=datetime.now(timezone.utc), status="active",
        )
        session.add(offer)
        session.flush()
        session.add(MatchAudit(offer_id=offer.id, product_variant_id=variant.id, method="test", confidence=Decimal("1.000")))
        session.commit()
        result = search_catalog(session, "Dior Sauvage EDP 200 ml")
        assert result["count"] == 0
        assert result["offer_count"] == 0
    finally:
        session.close()
        engine.dispose()

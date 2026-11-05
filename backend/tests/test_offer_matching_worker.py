from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.matching.offer_matcher import match_staged_offer
from app.models import Base, Brand, CanonicalIdentityReview, Fragrance, IngestionRaw, ProductVariant, Store
from app.services.product_normalization import normalize_product
from app.workers.matching_worker import match_pending_offers


def setup_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        brand = Brand(name="Christian Dior", slug="christian-dior",
                      normalized_name="christian dior")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug="sauvage")
        session.add(fragrance)
        session.flush()
        identity = normalize_product("Dior", "Dior Sauvage Eau de Parfum 100 ml")
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="edp", size_ml=100,
            canonical_key=identity.canonical_key,
        )
        session.add(variant)
        store = Store(name="Test Shop", slug="test-shop", currency="EUR", status="active")
        session.add(store)
        session.flush()
        raw = IngestionRaw(
            store_id=store.id,
            external_product_id="sku-100",
            raw_payload={
                "store": "test-shop", "externalProductId": "sku-100",
                "brand": "Dior", "title": "Dior Sauvage Eau de Parfum 100 ml",
                "fragrance": "sauvage", "concentration": "edp", "sizeMl": 100,
                "gtin": None, "url": "https://shop.example/item/sku-100",
                "price": 90.0, "currency": "EUR", "availability": "in_stock",
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "source": "fixture",
            },
            status="pending",
        )
        session.add(raw)
        session.commit()
        return factory, variant.id, raw.id


def test_exact_canonical_key_match_assigns_variant():
    factory, variant_id, raw_id = setup_db()
    with factory() as session:
        decision = match_staged_offer(session, raw_id)
        raw = session.get(IngestionRaw, raw_id)
        assert decision.status == "matched"
        assert decision.method == "canonical_key_exact"
        assert decision.confidence == Decimal("0.990")
        assert raw.product_variant_id == variant_id
        assert raw.status == "matched"


def test_batch_worker_leaves_unknown_identity_unmatched():
    factory, _variant_id, raw_id = setup_db()
    with factory() as session:
        raw = session.get(IngestionRaw, raw_id)
        payload = dict(raw.raw_payload)
        payload["title"] = "Dior Unknown Fragrance Eau de Parfum 100 ml"
        raw.raw_payload = payload
        session.commit()
    result = match_pending_offers(factory)
    with factory() as session:
        raw = session.get(IngestionRaw, raw_id)
        reviews = session.scalars(select(CanonicalIdentityReview)).all()
    assert result == {"processed": 1, "matched": 0, "unmatched": 1}
    assert raw.status == "unmatched"
    assert raw.product_variant_id is None
    assert raw.rejection_reason == "no_exact_canonical_variant"
    assert len(reviews) == 1
    assert reviews[0].status == "pending"
    assert reviews[0].reason == "no_exact_match"


def test_match_worker_does_not_reprocess_promoted_or_rejected_rows():
    factory, _variant_id, raw_id = setup_db()
    with factory() as session:
        raw = session.get(IngestionRaw, raw_id)
        raw.status = "rejected"
        session.commit()
    assert match_pending_offers(factory) == {
        "processed": 0, "matched": 0, "unmatched": 0,
    }


def test_gtin_conflict_is_not_auto_matched():
    factory, variant_id, raw_id = setup_db()
    with factory() as session:
        variant = session.get(ProductVariant, variant_id)
        variant.gtin = "4006381333931"
        raw = session.get(IngestionRaw, raw_id)
        payload = dict(raw.raw_payload)
        payload["gtin"] = "4006381333931"
        payload["title"] = "Dior Homme Eau de Toilette 100 ml"
        payload["concentration"] = "edt"
        raw.raw_payload = payload
        session.commit()
    with factory() as session:
        decision = match_staged_offer(session, raw_id)
        raw = session.get(IngestionRaw, raw_id)
        assert decision.status == "unmatched"
        assert decision.method == "gtin_identity_conflict"
        assert raw.product_variant_id is None
        assert raw.status == "unmatched"


def test_invalid_supplied_gtin_is_sent_to_review_not_canonical_auto_match():
    factory, variant_id, raw_id = setup_db()
    with factory() as session:
        raw = session.get(IngestionRaw, raw_id)
        payload = dict(raw.raw_payload)
        payload["gtin"] = "4006381333932"  # invalid check digit
        raw.raw_payload = payload
        session.commit()
    with factory() as session:
        decision = match_staged_offer(session, raw_id)
        raw = session.get(IngestionRaw, raw_id)
        reviews = session.scalars(select(CanonicalIdentityReview)).all()
        assert decision.status == "unmatched"
        assert decision.method == "invalid_gtin_review"
        assert raw.product_variant_id is None
        assert raw.status == "unmatched"
        assert len(reviews) == 1
        assert reviews[0].reason == "invalid_gtin_review"


def _bplatz_liquid_brun_fixture_record():
    import json
    from pathlib import Path
    from app.connectors import BplatzConnector
    from scrapers.bplatz import scraper

    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "bplatz" / "liquid-brun-54015243419916.raw.html"
    metadata = json.loads(
        (root / "tests" / "fixtures" / "bplatz" / "liquid-brun-54015243419916.meta.json")
        .read_text(encoding="utf-8")
    )
    html = fixture.read_text(encoding="utf-8")
    parsed = scraper.parse_product_html(
        html, metadata["url_final"], "French Avenue Liquid Brun"
    )
    assert parsed is not None
    records = BplatzConnector().parse_raw(parsed)
    assert len(records) == 1
    return records[0]


def _bplatz_liquid_brun_matching_db(record, *, duplicate_gtin=False):
    from app.models import Brand, Fragrance, ProductVariant, Store
    from app.services.product_normalization import normalize_product

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    identity = normalize_product(
        record.brand, record.title,
        concentration=record.concentration, size_ml=record.size_ml,
    )
    with factory() as session:
        brand = Brand(
            name=record.brand, slug="french-avenue",
            normalized_name="french avenue",
        )
        session.add(brand)
        session.flush()
        fragrance = Fragrance(
            brand_id=brand.id, name=record.fragrance,
            slug="liquid-brun",
        )
        session.add(fragrance)
        session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id,
            concentration="edp",
            size_ml=100,
            gtin="4006381333931" if duplicate_gtin else None,
            canonical_key=identity.canonical_key,
        )
        session.add(variant)
        if duplicate_gtin:
            session.add(ProductVariant(
                fragrance_id=fragrance.id,
                concentration="edp",
                size_ml=50,
                gtin="4006381333931",
                canonical_key="french-avenue|liquid-brun|edp|50|standard",
            ))
        store = Store(
            name="Bplatz", slug="bplatz", domain="bplatz.de",
            country="DE", currency="EUR", status="active",
        )
        session.add(store)
        session.flush()
        raw = IngestionRaw(
            store_id=store.id,
            external_product_id=record.external_product_id,
            raw_payload=record.to_dict(),
            status="pending",
        )
        session.add(raw)
        session.commit()
        return engine, factory, variant.id, raw.id


def test_bplatz_liquid_brun_wrong_size_is_not_matched_to_100ml_variant():
    record = _bplatz_liquid_brun_fixture_record()
    engine, factory, _variant_id, raw_id = _bplatz_liquid_brun_matching_db(record)
    try:
        with factory() as session:
            raw = session.get(IngestionRaw, raw_id)
            payload = dict(raw.raw_payload)
            payload["sizeMl"] = 50
            payload["title"] = "French Avenue Liquid Brun Eau de Parfum 50 ml"
            raw.raw_payload = payload
            session.commit()

        with factory() as session:
            decision = match_staged_offer(session, raw_id)
            raw = session.get(IngestionRaw, raw_id)
            reviews = session.scalars(select(CanonicalIdentityReview)).all()

        assert decision.status == "unmatched"
        assert decision.method == "no_exact_match"
        assert decision.product_variant_id is None
        assert raw.status == "unmatched"
        assert raw.product_variant_id is None
        assert raw.rejection_reason == "no_exact_canonical_variant"
        assert len(reviews) == 1
        assert reviews[0].reason == "no_exact_match"
    finally:
        engine.dispose()


def test_bplatz_liquid_brun_duplicate_gtin_is_held_for_ambiguous_identity_review():
    record = _bplatz_liquid_brun_fixture_record()
    engine, factory, _variant_id, raw_id = _bplatz_liquid_brun_matching_db(
        record, duplicate_gtin=True
    )
    try:
        with factory() as session:
            raw = session.get(IngestionRaw, raw_id)
            payload = dict(raw.raw_payload)
            # Valid test GTIN deliberately assigned to two canonical variants.
            payload["gtin"] = "4006381333931"
            raw.raw_payload = payload
            session.commit()

        with factory() as session:
            decision = match_staged_offer(session, raw_id)
            raw = session.get(IngestionRaw, raw_id)
            reviews = session.scalars(select(CanonicalIdentityReview)).all()

        assert decision.status == "unmatched"
        assert decision.method == "gtin_ambiguous"
        assert decision.product_variant_id is None
        assert raw.status == "unmatched"
        assert raw.product_variant_id is None
        assert raw.rejection_reason == "multiple_canonical_variants_share_gtin"
        assert len(reviews) == 1
        assert reviews[0].reason == "gtin_ambiguous"
    finally:
        engine.dispose()

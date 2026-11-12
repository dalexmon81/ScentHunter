from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import (
    Base, Brand, Fragrance, ProductVariant, Store, Offer, PriceHistory,
    IngestionRaw,
)
from app.services.notino_phase2_adapter import persist_notino_record


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        brand = Brand(name="Test Brand", slug="test-brand", normalized_name="test brand")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(
            brand_id=brand.id, name="Test Fragrance", slug="test-fragrance",
        )
        session.add(fragrance)
        session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id, concentration="EDP", size_ml=100,
            gtin="4006381333931", canonical_key="test|fragrance|edp|100",
        )
        store = Store(
            name="NOTINO.fr", slug="notino-fr", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        session.add_all([variant, store])
        session.flush()
        ids = (store.id, variant.id)
    return engine, ids


def _record(external_id: str, *, price: str = "49.90", **changes):
    record = {
        "external_id": external_id,
        "gtin": "4006381333931",
        "price": price,
        "sale_price": None,
        "currency": "EUR",
        "availability": "in stock",
        "affiliate_url": (
            "https://www.anrdoezrs.net/click-test?url="
            + quote(f"https://www.notino.fr/p/{external_id}", safe="")
        ),
        "source_last_updated": "2026-11-10T12:00:00Z",
        "captured_at": "2026-11-10T12:00:00Z",
    }
    record.update(changes)
    return record


def test_distinct_notino_external_ids_create_distinct_offers_for_same_variant():
    engine, (store_id, variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            first = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-ONE"),
            )
            second = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-TWO"),
            )
            assert first.status == second.status == "promoted"
            assert first.offer_id != second.offer_id
            assert first.product_variant_id == second.product_variant_id == variant_id

        with Session(engine) as session:
            offers = session.scalars(select(Offer).order_by(Offer.external_product_id)).all()
            assert len(offers) == 2
            assert {offer.external_product_id for offer in offers} == {"SKU-ONE", "SKU-TWO"}
            assert all(offer.product_variant_id == variant_id for offer in offers)
    finally:
        engine.dispose()


def test_repeat_notino_external_id_updates_same_offer_and_appends_history():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            first = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-ONE"),
            )
        with Session(engine) as session, session.begin():
            second = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-ONE", price="39.90", captured_at="2026-11-10T12:01:00Z"),
            )
            assert second.status == "promoted"
            assert second.offer_id == first.offer_id

        with Session(engine) as session:
            offers = session.scalars(select(Offer)).all()
            history = session.scalars(
                select(PriceHistory).where(PriceHistory.offer_id == first.offer_id)
            ).all()
            assert len(offers) == 1
            assert offers[0].price == Decimal("39.90")
            assert len(history) == 2
            assert session.get(IngestionRaw, second.ingestion_raw_id).status == "promoted"
    finally:
        engine.dispose()


def test_unmatched_gtin_stays_pending_and_is_not_published():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-UNKNOWN", gtin="4006381333948"),
            )
            assert result.status == "pending"
            assert result.offer_id is None
            assert result.reason == "gtin_not_in_canonical_catalog"

        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "pending"
            assert raw.product_variant_id is None
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_unknown_availability_is_matched_but_not_promoted():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-PREORDER", availability="preorder"),
            )
            assert result.status == "matched"
            assert result.offer_id is None
            assert result.reason == "availability_not_explicit"

        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "matched"
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_invalid_affiliate_clickout_is_matched_but_not_promoted():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record(
                    "SKU-NOT-AFFILIATE",
                    affiliate_url="https://www.notino.fr/p/SKU-NOT-AFFILIATE",
                ),
            )
            assert result.status == "matched"
            assert result.offer_id is None
            assert result.reason == "invalid_affiliate_url"

        with Session(engine) as session:
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_duplicate_gtin_stays_pending_for_manual_review():
    engine, (store_id, variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            original = session.get(ProductVariant, variant_id)
            duplicate = ProductVariant(
                fragrance_id=original.fragrance_id,
                concentration="EDT", size_ml=100,
                gtin="4006381333931",
                canonical_key="test|fragrance|edt|100",
            )
            session.add(duplicate)

        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id, raw_record=_record("SKU-AMBIGUOUS"),
            )
            assert result.status == "pending"
            assert result.offer_id is None
            assert result.product_variant_id is None
            assert result.reason == "gtin_matches_multiple_canonical_variants"

        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "pending"
            assert raw.product_variant_id is None
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()



def test_missing_external_id_stays_pending_and_is_not_published():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            record = _record("SKU-MISSING-ID")
            record["external_id"] = ""
            result = persist_notino_record(
                session, store_id=store_id, raw_record=record,
            )
            assert result.status == "pending"
            assert result.offer_id is None
            assert result.product_variant_id is None
            assert result.reason == "missing_external_product_id"

        with Session(engine) as session:
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert raw is not None and raw.status == "pending"
            assert raw.product_variant_id is None
            assert raw.rejection_reason == "missing_external_product_id"
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_invalid_gtin_check_digit_stays_pending():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            result = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-BAD-GTIN", gtin="4006381333932"),
            )
            assert result.status == "pending"
            assert result.reason == "invalid_gtin_check_digit"
            assert result.offer_id is None
        with Session(engine) as session:
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_missing_or_timezone_naive_source_timestamp_is_not_promoted():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            missing = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-NO-TIME", captured_at=""),
            )
            naive = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-NAIVE-TIME", captured_at="2026-11-10T12:00:00"),
            )
            assert missing.reason == "missing_source_observation_timestamp"
            assert naive.reason == "invalid_source_observation_timestamp"
            assert missing.status == naive.status == "matched"
        with Session(engine) as session:
            assert session.scalars(select(Offer)).all() == []
    finally:
        engine.dispose()


def test_older_feed_observation_cannot_overwrite_newer_offer():
    engine, (store_id, _variant_id) = _database()
    try:
        with Session(engine) as session, session.begin():
            newest = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-ORDERED", price="29.90", captured_at="2026-11-10T12:10:00Z"),
            )
            stale = persist_notino_record(
                session, store_id=store_id,
                raw_record=_record("SKU-ORDERED", price="59.90", captured_at="2026-11-10T12:05:00Z"),
            )
            assert newest.status == "promoted"
            assert stale.status == "stale"
            assert stale.reason == "source_observation_not_newer_than_stored_offer"
            assert stale.offer_id is None
        with Session(engine) as session:
            offers = session.scalars(select(Offer)).all()
            assert len(offers) == 1
            assert offers[0].price == Decimal("29.90")
            assert offers[0].captured_at.isoformat().startswith("2026-11-10T12:10:00")
            history = session.scalars(select(PriceHistory).where(PriceHistory.offer_id == newest.offer_id)).all()
            assert len(history) == 1
            assert history[0].price == Decimal("29.90")
    finally:
        engine.dispose()



def test_retailer_only_snapshot_rejects_gift_set_when_feed_title_hides_it_in_url():
    from datetime import datetime, timezone

    import pytest

    from app.services.notino_feed_listings import refresh_notino_listings

    destination = (
        "https://www.notino.fr/rasasi/hawas-ice-coffret-cadeau-pour-homme/p-123456/"
    )
    affiliate = (
        "https://www.anrdoezrs.net/click-101918103-13485502?url="
        + __import__("urllib.parse", fromlist=["quote"]).quote(destination, safe="")
    )
    row = {
        "id": "HAWAS-ICE-GIFT-SET",
        "brand": "Rasasi",
        # Some affiliate-feed rows omit the gift-set wording from their title.
        "title": "Rasasi Hawas Ice",
        "link": affiliate,
        "last_updated": "2026-11-12T05:00:00+00:00",
        "availability": "in stock",
        "price": "32.50 EUR",
        "size": "",
    }

    with pytest.raises(ValueError, match="no_valid_listings"):
        refresh_notino_listings(
            session=None,
            rows=[row],
            captured_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
        )


def test_legacy_notino_gift_set_is_removed_even_when_affiliate_url_wraps_destination():
    from main import _merge_notino_phase2_offers

    gift_set = {
        "store": "notino",
        "name": "Rasasi Hawas Ice",
        "price": 32.50,
        "url": (
            "https://www.kqzyfj.com/click-101918103-13485502?"
            "url=https%3A%2F%2Fwww.notino.fr%2Frasasi%2F"
            "hawas-ice-coffret-cadeau-pour-homme%2Fp-123456%2F"
        ),
    }
    normal_offer = {
        "store": "notino",
        "name": "Rasasi Hawas Ice Eau de Parfum 100 ml",
        "price": 37.40,
        "url": "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/",
    }

    merged = _merge_notino_phase2_offers([], [gift_set, normal_offer])

    assert gift_set not in merged
    assert normal_offer in merged



def test_non_fragrance_bundle_filter_is_generic_across_brands_and_languages():
    from main import _is_non_fragrance_offer
    from urllib.parse import quote

    cases = [
        ("Dior Sauvage", "https://www.notino.fr/dior/sauvage-coffret-cadeau/p-1/"),
        ("Chanel Coco Mademoiselle", "https://www.notino.fr/chanel/coco-mademoiselle-gift-set/p-2/"),
        ("YSL Libre", "https://www.notino.fr/yves-saint-laurent/libre-set-regalo/p-3/"),
        ("Armani My Way", "https://www.notino.fr/armani/my-way-giftbox/p-4/"),
        ("Paco Rabanne 1 Million", "https://www.notino.fr/paco-rabanne/1-million-discovery-set/p-5/"),
        ("Prada Paradoxe", "https://www.notino.fr/prada/paradoxe-fragrance-set/p-6/"),
        ("Jean Paul Gaultier Le Male", "https://www.notino.fr/jpg/le-male-coffret/p-7/"),
        ("Rasasi Hawas Ice", "https://www.notino.fr/rasasi/hawas-ice-duo/p-8/"),
        ("Lattafa Asad", "https://www.notino.fr/lattafa/asad-pack-regalo/p-9/"),
        ("Versace Eros", "https://www.notino.fr/versace/eros-bundle/p-10/"),
    ]

    for title, destination in cases:
        wrapped = "https://www.anrdoezrs.net/click?url=" + quote(destination, safe="")
        assert _is_non_fragrance_offer({
            "store": "notino", "title": title, "url": wrapped, "price": 29.90,
        }), f"bundle escaped generic filter: {title} -> {destination}"

    genuine = [
        {"title": "Dior Sauvage Eau de Parfum 100 ml",
         "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-11/"},
        {"title": "Chanel Coco Mademoiselle Eau de Parfum 100 ml",
         "url": "https://www.notino.fr/chanel/coco-mademoiselle-eau-de-parfum/p-12/"},
        {"title": "Rasasi Hawas Ice Eau de Parfum 100 ml",
         "url": "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-13/"},
    ]
    for offer in genuine:
        assert not _is_non_fragrance_offer(offer), f"valid standalone perfume was rejected: {offer}"

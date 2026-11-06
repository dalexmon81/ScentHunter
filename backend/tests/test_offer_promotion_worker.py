from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, Brand, Fragrance, IngestionRaw, MatchAudit, Offer,
    PriceHistory, ProductVariant, Store,
)
from app.services.product_normalization import normalize_product
from app.workers.offer_promotion import promote_matched_offers


def setup_db(availability="in_stock", captured_at="2025-01-02T03:04:05+00:00"):
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
        store = Store(name="Test Shop", slug="test-shop", currency="EUR", offer_ttl_minutes=1440, status="active")
        session.add_all([variant, store])
        session.flush()
        raw = IngestionRaw(
            store_id=store.id, external_product_id="sku-100",
            raw_payload={
                "store": "test-shop", "externalProductId": "sku-100",
                "brand": "Dior", "fragrance": "Sauvage",
                "title": "Dior Sauvage Eau de Parfum 100 ml",
                "concentration": "edp", "sizeMl": 100, "gtin": None,
                "url": "https://shop.example/item/sku-100",
                "price": 90.50, "currency": "EUR", "availability": availability,
                "capturedAt": captured_at,
                "source": "fixture",
            },
            status="matched", product_variant_id=variant.id,
            match_method="canonical_key_exact", match_confidence=Decimal("0.990"),
        )
        session.add(raw)
        session.commit()
        return factory, raw.id


def test_promotion_creates_offer_history_and_audit():
    factory, raw_id = setup_db()
    assert promote_matched_offers(factory) == {
        "processed": 1, "published": 1, "blocked": 0,
    }
    with factory() as session:
        offers = session.scalars(select(Offer)).all()
        history = session.scalars(select(PriceHistory)).all()
        audits = session.scalars(select(MatchAudit)).all()
        raw = session.get(IngestionRaw, raw_id)
        assert len(offers) == len(history) == len(audits) == 1
        assert offers[0].price == Decimal("90.50")
        assert offers[0].status == "active"
        expected_capture = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        assert offers[0].captured_at.replace(tzinfo=timezone.utc) == expected_capture
        assert history[0].captured_at.replace(tzinfo=timezone.utc) == expected_capture
        assert history[0].price == Decimal("90.50")
        assert audits[0].method == "canonical_key_exact"
        assert raw.status == "promoted"


def test_preorder_is_retained_but_not_published_until_policy_is_enabled():
    factory, raw_id = setup_db("preorder")
    assert promote_matched_offers(factory) == {
        "processed": 1, "published": 0, "blocked": 1,
    }
    with factory() as session:
        offer = session.scalar(select(Offer))
        raw = session.get(IngestionRaw, raw_id)
        assert offer is None
        assert raw.status == "matched"
        assert raw.rejection_reason.startswith("promotion_blocked:")


def test_worker_ignores_unmatched_rows():
    factory, raw_id = setup_db()
    with factory() as session:
        raw = session.get(IngestionRaw, raw_id)
        raw.status = "unmatched"
        raw.product_variant_id = None
        session.commit()
    assert promote_matched_offers(factory) == {
        "processed": 0, "published": 0, "blocked": 0,
    }
    with factory() as session:
        assert session.scalar(select(Offer)) is None



def test_blocked_old_row_does_not_starve_later_promotion_batch():
    factory, blocked_id = setup_db("unknown")
    with factory() as session:
        blocked = session.get(IngestionRaw, blocked_id)
        later = IngestionRaw(
            store_id=blocked.store_id,
            external_product_id="sku-101",
            raw_payload={
                **blocked.raw_payload,
                "externalProductId": "sku-101",
                "url": "https://shop.example/item/sku-101",
                "availability": "in_stock",
            },
            status="matched",
            product_variant_id=blocked.product_variant_id,
            match_method=blocked.match_method,
            match_confidence=blocked.match_confidence,
        )
        session.add(later)
        session.commit()
        later_id = later.id

    first = promote_matched_offers(factory, limit=1)
    second = promote_matched_offers(factory, limit=1)

    assert first == {"processed": 1, "published": 0, "blocked": 1}
    assert second == {"processed": 1, "published": 1, "blocked": 0}
    with factory() as session:
        blocked = session.get(IngestionRaw, blocked_id)
        later = session.get(IngestionRaw, later_id)
        offers = session.scalars(select(Offer)).all()
        assert blocked.status == "matched"
        assert blocked.rejection_reason.startswith("promotion_blocked:")
        assert later.status == "promoted"
        assert len(offers) == 1
        assert offers[0].external_product_id == "sku-101"


def test_distinct_retailer_listings_for_same_variant_create_distinct_offers():
    factory, first_raw_id = setup_db()
    with factory() as session:
        first = session.get(IngestionRaw, first_raw_id)
        second = IngestionRaw(
            store_id=first.store_id,
            external_product_id="sku-duplicate-listing",
            raw_payload={
                **first.raw_payload,
                "externalProductId": "sku-duplicate-listing",
                "url": "https://shop.example/item/sku-duplicate-listing",
                "price": 87.25,
            },
            status="matched",
            product_variant_id=first.product_variant_id,
            match_method=first.match_method,
            match_confidence=first.match_confidence,
        )
        session.add(second)
        session.commit()
        second_id = second.id

    assert promote_matched_offers(factory) == {
        "processed": 2, "published": 2, "blocked": 0,
    }
    with factory() as session:
        offers = session.scalars(select(Offer).order_by(Offer.external_product_id)).all()
        assert len(offers) == 2
        assert {offer.external_product_id for offer in offers} == {
            "sku-100", "sku-duplicate-listing",
        }
        assert {offer.price for offer in offers} == {
            Decimal("90.50"), Decimal("87.25"),
        }


def test_http_offer_url_is_blocked_by_publication_gate():
    factory, raw_id = setup_db()
    with factory() as session:
        raw = session.get(IngestionRaw, raw_id)
        raw.raw_payload = {
            **raw.raw_payload,
            "url": "http://shop.example/item/sku-100",
        }
        session.commit()
    assert promote_matched_offers(factory) == {
        "processed": 1, "published": 0, "blocked": 1,
    }
    with factory() as session:
        assert session.scalar(select(Offer)) is None
        raw = session.get(IngestionRaw, raw_id)
        assert raw.status == "matched"
        assert raw.rejection_reason.startswith("promotion_blocked:")



def test_invalid_explicit_source_capture_timestamp_blocks_publication():
    factory, raw_id = setup_db(captured_at="not-a-timestamp")
    assert promote_matched_offers(factory) == {
        "processed": 1, "published": 0, "blocked": 1,
    }
    with factory() as session:
        assert session.scalar(select(Offer)) is None
        raw = session.get(IngestionRaw, raw_id)
        assert raw.status == "matched"
        assert "capturedAt must be a valid ISO-8601 timestamp" in raw.rejection_reason

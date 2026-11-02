from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Base, Brand, Fragrance, ProductVariant, Store, IngestionRaw, Offer, PriceHistory, MatchAudit
from app.services.ingestion_persistence import PromotionRejected, stage_raw_offer, record_match, promote_offer


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed(session):
    store = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
    brand = Brand(name="French Avenue", slug="french-avenue", normalized_name="french avenue")
    session.add_all([store, brand])
    session.flush()
    fragrance = Fragrance(brand_id=brand.id, name="Liquid Brun", slug="liquid-brun")
    session.add(fragrance)
    session.flush()
    variant = ProductVariant(fragrance_id=fragrance.id, concentration="EDP",
        size_ml=100, canonical_key="french-avenue|liquid-brun|edp|100")
    session.add(variant)
    session.flush()
    return store, variant


def test_real_parser_normalizer_matcher_and_sqlalchemy_promotion():
    from scrapers.bplatz.scraper import parse_product_html
    from scenthunter_next_engine.next_engine_service import NextEngineService

    fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
    meta = json.loads((ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json").read_text())
    parsed = parse_product_html(fixture.read_text(), meta["url_final"], "French Avenue Liquid Brun")
    assert parsed is not None
    record = {
        "raw_name": parsed["name"], "brand_raw": parsed["brand"],
        "size_ml": parsed["size_ml"], "price": parsed["price_num"],
        "currency": parsed["offer"]["currency"], "product_url": parsed["url"],
        "availability": parsed["availability"], "sku": parsed["sku"], "gtin": parsed["gtin"],
    }
    pipeline = NextEngineService.from_catalog_file(ROOT / "backend/product_catalog.json")
    result = pipeline.process_records([record], retailer="Bplatz")
    matched = result.aggregation.groups[0]
    assert (matched.canonical_product_id, matched.canonical_variant_id) == (
        "SH-0030", "VAR-f87146c82d167f4c")
    normalized = matched.offers[0]

    engine = _engine()
    try:
        with Session(engine) as session, session.begin():
            store, variant = _seed(session)
            raw_id = stage_raw_offer(session, store_id=store.id,
                raw_payload=record, external_product_id=parsed["sku"])
            assert record_match(session, ingestion_raw_id=raw_id,
                product_variant_id=variant.id, method="real_catalog_matcher",
                confidence=Decimal("0.990")) == "matched"
            offer_id = promote_offer(session, ingestion_raw_id=raw_id,
                price=normalized.price, currency=normalized.currency,
                url=normalized.product_url, availability=normalized.availability,
                source="bplatz_jsonld", confidence=Decimal("0.990"))
            variant_id = variant.id
        with Session(engine) as session:
            offer = session.get(Offer, offer_id)
            raw = session.get(IngestionRaw, raw_id)
            assert offer is not None and offer.product_variant_id == variant_id
            assert offer.ingestion_raw_id == raw_id
            assert raw is not None and raw.status == "promoted"
            assert session.scalar(select(PriceHistory).where(PriceHistory.offer_id == offer_id))
            assert session.scalar(select(MatchAudit).where(MatchAudit.offer_id == offer_id))
    finally:
        engine.dispose()


def test_unmatched_raw_is_kept_but_never_published():
    engine = _engine()
    try:
        with Session(engine) as session, session.begin():
            store, _variant = _seed(session)
            raw_id = stage_raw_offer(session, store_id=store.id, raw_payload={"title": "Liquid"})
            assert record_match(session, ingestion_raw_id=raw_id,
                product_variant_id=None, method="canonical_matcher") == "unmatched"
            with pytest.raises(PromotionRejected):
                promote_offer(session, ingestion_raw_id=raw_id, price=Decimal("40.00"),
                    currency="EUR", url="https://example.test/p",
                    availability="in_stock", source="test")
        with Session(engine) as session:
            raw = session.get(IngestionRaw, raw_id)
            assert raw.status == "unmatched" and raw.product_variant_id is None
            assert session.scalar(select(Offer.id)) is None
    finally:
        engine.dispose()


@pytest.mark.parametrize("changes", [
    {"price": Decimal("0")}, {"currency": "eur"},
    {"url": "file:///tmp/not-http"}, {"availability": "unknown"},
])
def test_invalid_offer_fields_block_promotion(changes):
    engine = _engine()
    try:
        with Session(engine) as session, session.begin():
            store, variant = _seed(session)
            raw_id = stage_raw_offer(session, store_id=store.id, raw_payload={"title": "Liquid"})
            record_match(session, ingestion_raw_id=raw_id,
                product_variant_id=variant.id, method="test")
            values = dict(price=Decimal("49.90"), currency="EUR",
                url="https://example.test/p", availability="in_stock", source="test")
            values.update(changes)
            with pytest.raises(PromotionRejected):
                promote_offer(session, ingestion_raw_id=raw_id, **values)
        with Session(engine) as session:
            assert session.scalar(select(Offer.id)) is None
            assert session.get(IngestionRaw, raw_id).status == "matched"
    finally:
        engine.dispose()

# CI includes the complete fixture suite alongside these SQLAlchemy persistence tests.

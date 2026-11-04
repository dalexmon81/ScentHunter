import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.base import OfferRecord
from app.models import Base, IngestionRaw, IngestionRun, Store
from app.workers.connector_ingestion import run_connector_once


class FakeConnector:
    store_key = "fake-store"
    source_kind = "fixture"

    def __init__(self, *, fail=False, invalid=False):
        self.fail = fail
        self.invalid = invalid

    async def discover_products(self):
        if self.fail:
            raise TimeoutError("temporary retailer timeout")
        return ({"externalProductId": "sku-1"},)

    async def fetch_offers(self, product_key):
        return (self.record(),)

    async def fetch_product(self, external_id):
        return None

    async def fetch_price_and_stock(self, offer_id):
        return None

    def parse_raw(self, raw):
        return ()

    def record(self):
        return OfferRecord(
            store=self.store_key,
            external_product_id="sku-1",
            brand="Dior",
            fragrance="sauvage",
            concentration="edp",
            size_ml=100,
            gtin=None,
            title="Dior Sauvage EDP 100 ml",
            url="https://shop.example/product/sku-1",
            price=Decimal("95.00"),
            currency="EUR",
            availability="unknown" if self.invalid else "in_stock",
            captured_at=datetime.now(timezone.utc).isoformat(),
            source=self.source_kind,
        )

    def validate_offer(self, offer):
        if self.invalid:
            return False, ("fixture_invalid",)
        return True, ()


def make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Store(name="Fake Store", slug="fake-store", currency="EUR", status="active"))
        session.commit()
    return factory


def test_worker_stages_valid_evidence_without_publishing():
    factory = make_session_factory()
    result = run_connector_once(FakeConnector(), factory)
    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
        run = session.scalar(select(IngestionRun))
    assert result == {
        "store": "fake-store", "status": "completed", "discovered": 1,
        "staged": 1, "rejected": 0, "published": 0,
    }
    assert raw.status == "pending"
    assert raw.external_product_id == "sku-1"
    assert run.status == "completed"
    assert run.offers_created == 0


def test_worker_keeps_invalid_evidence_rejected():
    factory = make_session_factory()
    result = run_connector_once(FakeConnector(invalid=True), factory)
    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
    assert result["rejected"] == 1
    assert raw.status == "rejected"
    assert raw.rejection_reason == "fixture_invalid"


def test_worker_quarantines_only_after_repeated_store_failures():
    factory = make_session_factory()
    first = run_connector_once(FakeConnector(fail=True), factory, quarantine_after=2)
    second = run_connector_once(FakeConnector(fail=True), factory, quarantine_after=2)
    with factory() as session:
        store = session.scalar(select(Store))
    assert first["status"] == "failed"
    assert second["status"] == "quarantined"
    assert store.status == "quarantined"


def test_notino_fixture_matches_and_promotes_exact_dior_sauvage_edp_100ml():
    from app.connectors.notino import NotinoAffiliateFeedConnector
    from app.matching.offer_matcher import match_staged_offer
    from app.models import Brand, Fragrance, ProductVariant, Offer, PriceHistory, MatchAudit
    from app.services.ingestion_persistence import promote_offer

    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss xmlns:g="http://base.google.com/ns/1.0"><channel><item>
      <g:id>notino-dior-sauvage-edp-100</g:id>
      <g:title>Dior Sauvage Eau de Parfum 100 ml</g:title>
      <g:brand>Dior</g:brand>
      <g:price>99.90 EUR</g:price>
      <g:availability>in stock</g:availability>
      <g:link>https://www.notino.fr/dior/sauvage-eau-de-parfum/</g:link>
      <g:size>100 ml</g:size>
    </item></channel></rss>"""

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        brand = Brand(name="Dior", slug="dior", normalized_name="christian dior")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug="sauvage")
        session.add(fragrance)
        session.flush()
        variant = ProductVariant(
            fragrance_id=fragrance.id,
            concentration="Eau de Parfum",
            size_ml=100,
            canonical_key="christian-dior|sauvage|edp|100|standard",
        )
        session.add(variant)
        session.add(Store(
            name="Notino", slug="notino", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        ))
        session.commit()

    connector = NotinoAffiliateFeedConnector(feed_loader=lambda: xml)
    result = run_connector_once(connector, factory)
    assert result == {
        "store": "notino", "status": "completed", "discovered": 1,
        "staged": 1, "rejected": 0, "published": 0,
    }
    assert connector.raw_evidence_for() == xml
    record = connector._offers[0]
    assert record.brand == "Dior"
    assert record.fragrance == "sauvage"
    assert record.concentration == "edp"
    assert record.size_ml == 100
    assert record.price == Decimal("99.90")
    assert record.currency == "EUR"
    assert record.availability == "in_stock"

    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
        decision = match_staged_offer(session, raw.id)
        assert decision.status == "matched"
        assert decision.method == "canonical_key_exact"
        offer_id = promote_offer(
            session,
            ingestion_raw_id=raw.id,
            price=record.price,
            currency=record.currency,
            url=record.url,
            availability=record.availability,
            source=record.source,
            confidence=decision.confidence,
        )
        session.commit()
        offer = session.get(Offer, offer_id)
        assert offer is not None
        assert offer.status == "active"
        assert offer.product_variant_id == decision.product_variant_id
        assert offer.price == Decimal("99.90")
        assert offer.currency == "EUR"
        assert offer.availability == "in_stock"
        assert raw.status == "promoted"
        assert len(list(session.scalars(select(PriceHistory).where(
            PriceHistory.offer_id == offer_id
        )))) == 1
        assert len(list(session.scalars(select(MatchAudit).where(
            MatchAudit.offer_id == offer_id
        )))) == 1
    engine.dispose()


def test_notino_live_preflight_requires_exact_and_explicitly_available_candidate():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "notino_pilot_preflight.py"
    spec = importlib.util.spec_from_file_location("notino_pilot_preflight", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    record = OfferRecord(
        store="notino",
        external_product_id="fixture-notino-sauvage-edp-100",
        brand="Dior",
        fragrance="sauvage",
        concentration="edp",
        size_ml=100,
        gtin=None,
        title="Dior Sauvage Eau de Parfum 100 ml",
        url="https://www.notino.fr/dior/sauvage-eau-de-parfum/",
        price=Decimal("99.90"),
        currency="EUR",
        availability="in_stock",
        captured_at=datetime.now(timezone.utc).isoformat(),
        source="authorized_affiliate_xml",
    )
    report = module.summarize_candidates([record])
    assert report["status"] == "ready_for_staging_review"
    assert report["ready_for_staging_review"] is True
    assert report["database_written"] is False
    assert report["offer_published"] is False

    unknown = OfferRecord(**{**record.__dict__, "availability": "unknown"})
    blocked = module.summarize_candidates([unknown])
    assert blocked["status"] == "candidate_requires_availability_review"
    assert blocked["ready_for_staging_review"] is False

    wrong_concentration = OfferRecord(**{**record.__dict__, "concentration": "edt"})
    unmatched = module.summarize_candidates([wrong_concentration])
    assert unmatched["status"] == "no_exact_product"
    assert unmatched["exact_candidate_count"] == 0


def test_bplatz_saved_fixture_stages_matches_and_promotes_exact_offer():
    from pathlib import Path
    from app.connectors import BplatzConnector
    from app.matching.offer_matcher import match_staged_offer
    from app.models import Brand, Fragrance, ProductVariant, Offer, PriceHistory, MatchAudit
    from app.services.ingestion_persistence import promote_offer
    from scrapers.bplatz import scraper

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "connectors"
        / "bplatz-dior-sauvage-edp-100.html"
    )
    url = "https://en.bplatz.de/products/dior-sauvage-eau-de-parfum"
    html = fixture.read_text(encoding="utf-8")
    parsed = scraper.parse_product_html(html, url, "Dior Sauvage")
    assert parsed is not None
    connector = BplatzConnector()
    records = connector.parse_raw(parsed)
    assert len(records) == 1
    record = records[0]
    assert record.gtin is None  # Fixture carries no independently verified GTIN.

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        brand = Brand(name="Dior", slug="dior", normalized_name="christian dior")
        session.add(brand)
        session.flush()
        fragrance = Fragrance(brand_id=brand.id, name="Sauvage", slug="sauvage")
        session.add(fragrance)
        session.flush()
        session.add(ProductVariant(
            fragrance_id=fragrance.id,
            concentration="Eau de Parfum",
            size_ml=100,
            canonical_key="christian-dior|sauvage|edp|100|standard",
        ))
        session.add(Store(
            name="Bplatz", slug="bplatz", domain="en.bplatz.de",
            country="DE", currency="EUR", status="active",
        ))
        session.commit()

    # Exercise the real ingestion runner with the parsed fixture and no HTTP.
    async def discover_products():
        return ({"externalProductId": record.external_product_id, "url": record.url},)

    async def fetch_offers(_product_key):
        return (record,)

    connector.discover_products = discover_products
    connector.fetch_offers = fetch_offers
    result = run_connector_once(connector, factory)
    assert result == {
        "store": "bplatz", "status": "completed", "discovered": 1,
        "staged": 1, "rejected": 0, "published": 0,
    }

    with factory() as session:
        raw = session.scalar(select(IngestionRaw))
        decision = match_staged_offer(session, raw.id)
        assert decision.status == "matched"
        assert decision.method == "canonical_key_exact"
        offer_id = promote_offer(
            session,
            ingestion_raw_id=raw.id,
            price=record.price,
            currency=record.currency,
            url=record.url,
            availability=record.availability,
            source=record.source,
            confidence=decision.confidence,
        )
        session.commit()
        offer = session.get(Offer, offer_id)
        assert offer is not None and offer.status == "active"
        assert offer.store_id == raw.store_id
        assert offer.product_variant_id == decision.product_variant_id
        assert offer.price == Decimal("89.90")
        assert offer.currency == "EUR"
        assert offer.availability == "in_stock"
        assert raw.status == "promoted"
        assert len(list(session.scalars(select(PriceHistory).where(
            PriceHistory.offer_id == offer_id
        )))) == 1
        assert len(list(session.scalars(select(MatchAudit).where(
            MatchAudit.offer_id == offer_id
        )))) == 1
    engine.dispose()

import asyncio

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.connectors.base import OfferRecord
from app.models import Base, IngestionRaw, IngestionRun, Store, StoreAuthorization
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
        store = Store(name="Fake Store", slug="fake-store", currency="EUR", status="active")
        session.add(store)
        session.flush()
        session.add(StoreAuthorization(
            store_id=store.id, status="approved", collection_method="other",
            scopes=["product_discovery", "offer_data"],
            authorization_reference="fixture-written-consent",
            approved_by="isolated-test", approved_at=datetime.now(timezone.utc), terms={},
        ))
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
    assert raw.rejection_reason == "availability_requires_review"


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
            country="FR", currency="EUR", offer_ttl_minutes=1440, status="active",
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


def test_notino_live_preflight_requires_exact_gtin_and_explicitly_available_candidate():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "notino_pilot_preflight.py"
    spec = importlib.util.spec_from_file_location("notino_pilot_preflight", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    record = OfferRecord(
        store="notino",
        external_product_id="fixture-notino-liquid-brun-edp-100",
        brand="French Avenue",
        fragrance="liquid brun",
        concentration="edp",
        size_ml=100,
        gtin="6290360375694",
        title="French Avenue Liquid Brun Eau de Parfum 100 ml",
        url="https://www.notino.fr/french-avenue/liquid-brun/",
        price=Decimal("29.00"),
        currency="EUR",
        availability="in_stock",
        captured_at=datetime.now(timezone.utc).isoformat(),
        source="authorized_affiliate_xml",
    )
    report = module.summarize_candidates([record])
    assert report["status"] == "ready_for_staging_review"
    assert report["ready_for_staging_review"] is True
    assert report["candidates"][0]["gtin_match"] is True
    assert report["database_written"] is False
    assert report["offer_published"] is False

    missing_gtin = OfferRecord(**{**record.__dict__, "gtin": None})
    blocked_gtin = module.summarize_candidates([missing_gtin])
    assert blocked_gtin["status"] == "candidate_requires_gtin_review"
    assert blocked_gtin["ready_for_staging_review"] is False

    wrong_gtin = OfferRecord(**{**record.__dict__, "gtin": "0000000000000"})
    blocked_mismatch = module.summarize_candidates([wrong_gtin])
    assert blocked_mismatch["status"] == "candidate_gtin_mismatch"
    assert blocked_mismatch["ready_for_staging_review"] is False

    unknown = OfferRecord(**{**record.__dict__, "availability": "unknown"})
    blocked_availability = module.summarize_candidates([unknown])
    assert blocked_availability["status"] == "candidate_requires_availability_review"
    assert blocked_availability["ready_for_staging_review"] is False

    wrong_concentration = OfferRecord(**{**record.__dict__, "concentration": "edt"})
    unmatched = module.summarize_candidates([wrong_concentration])
    assert unmatched["status"] == "no_exact_product"
    assert unmatched["exact_candidate_count"] == 0


def test_bplatz_bounded_product_fetch_uses_exact_url_without_discovery():
    import json
    from pathlib import Path
    from app.connectors.bplatz import BplatzConnector
    from app.services.product_normalization import normalize_product
    from app.matching.offer_matcher import match_staged_offer
    from app.models import Brand, Fragrance, ProductVariant

    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
    meta = json.loads(
        (root / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json").read_text()
    )
    from scrapers.bplatz.scraper import parse_product_html
    parsed = parse_product_html(
        fixture.read_text(encoding="utf-8"), meta["url_final"], "Liquid Brun"
    )
    assert parsed is not None
    calls = []

    def page_loader(url, query):
        calls.append((url, query))
        return parsed

    connector = BplatzConnector(page_loader=page_loader)
    records = asyncio.run(connector.fetch_product_url(meta["url_final"], "Liquid Brun"))
    assert len(records) == 1
    assert calls == [(meta["url_final"], "Liquid Brun")]
    record = records[0]
    assert record.brand == "French Avenue"
    assert record.fragrance == "liquid brun"
    assert record.concentration == "edp"
    assert record.size_ml == 100
    assert record.gtin == "6290360375694"
    assert record.price is not None and record.price > 0
    assert record.availability == "in_stock"

    identity = normalize_product(
        "French Avenue", "French Avenue Liquid Brun Eau de Parfum 100 ml"
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            brand = Brand(
                name="French Avenue", slug="french-avenue",
                normalized_name="french avenue",
            )
            session.add(brand)
            session.flush()
            fragrance = Fragrance(
                brand_id=brand.id, name="Liquid Brun", slug="liquid-brun",
            )
            session.add(fragrance)
            session.flush()
            variant = ProductVariant(
                fragrance_id=fragrance.id, concentration="edp",
                size_ml=100, canonical_key=identity.canonical_key,
            )
            store = Store(
                name="Bplatz", slug="bplatz", domain="bplatz.de",
                country="DE", currency="EUR", status="active",
            )
            session.add_all([variant, store])
            session.flush()
            raw = IngestionRaw(
                store_id=store.id,
                external_product_id=record.external_product_id,
                raw_payload=record.to_dict(),
                status="pending",
            )
            session.add(raw)
            session.commit()
            decision = match_staged_offer(session, raw.id)
            assert decision.status == "matched"
            assert decision.method == "canonical_key_exact"
            assert decision.product_variant_id == variant.id
    finally:
        engine.dispose()


def test_bplatz_manual_task_requires_access_reference_and_exact_product_url():
    from app.workers.ingestion_tasks import ingest_bounded_bplatz_product_url

    with pytest.raises(ValueError, match="authorization_reference_required"):
        ingest_bounded_bplatz_product_url.run(
            "https://bplatz.de/products/fragrance-world-liquid-brun-eau-de-parfum-100ml",
            "",
        )
    with pytest.raises(ValueError, match="exact_liquid_brun_100ml"):
        ingest_bounded_bplatz_product_url.run(
            "https://bplatz.de/products/another-fragrance",
            "Bplatz automated-access approval recorded",
        )


def test_discovery_failure_marks_its_own_run_without_touching_another_running_run(monkeypatch, tmp_path):
    from sqlalchemy.orm import sessionmaker
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'discovery-failure.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        store = Store(name="Fake Store", slug="fake-store", currency="EUR", status="active")
        session.add(store)
        session.flush()
        session.add(StoreAuthorization(
            store_id=store.id, status="approved", collection_method="other",
            scopes=["product_discovery", "offer_data"],
            authorization_reference="fixture-written-consent",
            approved_by="isolated-test", approved_at=datetime.now(timezone.utc), terms={},
        ))
        session.commit()
    with factory() as session:
        store = session.scalar(select(Store).where(Store.slug == "fake-store"))
        other_run = IngestionRun(store_id=store.id, status="running", errors=[])
        session.add(other_run)
        session.commit()
        other_run_id = other_run.id

    class FailingConnector(FakeConnector):
        pass

    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "get_connector", lambda _store_key: FailingConnector())
    monkeypatch.setattr(
        ingestion_tasks, "_run",
        lambda _coroutine: (_ for _ in ()).throw(TimeoutError("discovery timeout")),
    )

    with pytest.raises(TimeoutError, match="discovery timeout"):
        ingestion_tasks.discover_store_products.run("fake-store")

    with factory() as session:
        runs = list(session.scalars(
            select(IngestionRun).where(IngestionRun.store_id == store.id)
        ))
        untouched = session.get(IngestionRun, other_run_id)

    assert untouched.status == "running"
    assert sum(run.status == "failed" for run in runs) == 1
    assert sum(run.status == "running" for run in runs) == 1
    engine.dispose()



def test_legacy_sync_runner_is_not_part_of_the_production_celery_worker():
    from app.workers.celery_app import celery_app

    # The sync adapter exists for isolated fixtures and backwards-compatible
    # callers only. Production workers load and route the canonical task module.
    assert celery_app.conf.include == ["app.workers.ingestion_tasks"]
    assert all(
        "connector_ingestion" not in task_name
        for task_name in celery_app.conf.task_routes
    )

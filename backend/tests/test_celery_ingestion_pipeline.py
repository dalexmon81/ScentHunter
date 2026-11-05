from app.workers.celery_app import celery_app

def test_pipeline_declares_all_required_queues():
    names = {queue.name for queue in celery_app.conf.task_queues}
    assert {"discovery", "offers", "validation", "matching", "refresh", "dead_letter"} <= names

def test_pipeline_routes_jobs_to_separate_queues():
    routes = celery_app.conf.task_routes
    assert routes["app.workers.ingestion_tasks.discover_store_products"]["queue"] == "discovery"
    assert routes["app.workers.ingestion_tasks.fetch_store_offers"]["queue"] == "offers"
    assert routes["app.workers.ingestion_tasks.normalize_offer"]["queue"] == "validation"
    assert routes["app.workers.ingestion_tasks.validate_offer"]["queue"] == "validation"
    assert routes["app.workers.ingestion_tasks.match_offer_to_variant"]["queue"] == "matching"
    assert routes["app.workers.ingestion_tasks.promote_matched_offers_task"]["queue"] == "offers"
    assert routes["app.workers.ingestion_tasks.refresh_price_and_stock"]["queue"] == "refresh"
    assert routes["app.workers.ingestion_tasks.record_dead_letter"]["queue"] == "dead_letter"

def test_pipeline_beat_cadence_is_catalog_first():
    schedule = celery_app.conf.beat_schedule
    assert schedule["discover-store-products-daily"]["schedule"] == 86400.0
    assert schedule["refresh-known-active-offers-every-eight-hours"]["schedule"] == 28800.0
    assert schedule["refresh-known-active-offers-every-eight-hours"]["task"] == (
        "app.workers.ingestion_tasks.enqueue_offer_collection_for_configured_stores"
    )
    assert schedule["refresh-main-store-prices-every-thirty-minutes"]["schedule"] == 1800.0

def test_all_pipeline_jobs_are_registered_and_runtime_has_nine_connectors():
    import app.workers.ingestion_tasks  # noqa: F401
    from app.connectors.runtime_registry import build_connectors

    registered = set(celery_app.tasks)
    expected = {
        "app.workers.ingestion_tasks.discover_store_products",
        "app.workers.ingestion_tasks.fetch_store_offers",
        "app.workers.ingestion_tasks.normalize_offer",
        "app.workers.ingestion_tasks.validate_offer",
        "app.workers.ingestion_tasks.match_offer_to_variant",
        "app.workers.ingestion_tasks.promote_matched_offers_task",
        "app.workers.ingestion_tasks.refresh_price_and_stock",
        "app.workers.ingestion_tasks.quarantine_failed_connector",
        "app.workers.ingestion_tasks.reprocess_failed_offers",
        "app.workers.ingestion_tasks.record_dead_letter",
    }
    assert expected <= registered
    assert set(build_connectors()) == {
        "notino", "deloox", "easycosmetic", "sabina", "parfumzentrum",
        "perfumemarket", "parfumcity", "bplatz", "orioudh",
    }


def test_raw_artifact_model_stores_immutable_source_bytes():
    from app.models import IngestionArtifact

    table = IngestionArtifact.__table__
    assert {"artifact_format", "sha256", "size_bytes", "raw_data", "metadata_json"} <= set(table.columns.keys())
    assert table.c.sha256.type.length == 64
    assert table.c.raw_data.nullable is False


def test_raw_evidence_bytes_are_base64_encoded_for_json_payloads():
    import base64
    from app.workers.ingestion_tasks import _json_safe

    original = b"<feed><item>original</item></feed>"
    encoded = _json_safe(original)
    assert encoded["encoding"] == "base64"
    assert base64.b64decode(encoded["data"]) == original


def test_product_detail_refresh_can_be_enqueued_on_refresh_queue(monkeypatch):
    from app.workers import ingestion_tasks

    class FakeResult:
        id = "refresh-job-123"

    calls = {}
    def fake_apply_async(*, kwargs, queue):
        calls.update(kwargs=kwargs, queue=queue)
        return FakeResult()

    monkeypatch.setattr(ingestion_tasks.refresh_price_and_stock, "apply_async", fake_apply_async)
    result = ingestion_tasks.enqueue_product_detail_refresh("notino", "sku-123")
    assert result == "refresh-job-123"
    assert calls == {
        "kwargs": {"store_key": "notino", "offer_id": "sku-123"},
        "queue": "refresh",
    }


def test_dead_letter_model_is_durable_and_unique_per_task():
    from app.models import IngestionDeadLetter

    table = IngestionDeadLetter.__table__
    assert {"task_name", "task_id", "args_repr", "kwargs_repr", "error", "status"} <= set(table.columns.keys())
    assert any(constraint.name == "uq_ingestion_dead_letters_task_id" for constraint in table.constraints)


def test_periodic_discovery_uses_only_active_catalog_stores(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, Store
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'active-stores.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add_all([
            Store(name="Bplatz", slug="bplatz", currency="EUR", status="active"),
            Store(name="Notino", slug="notino", currency="EUR", status="inactive"),
        ])
        session.commit()
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "build_connectors", lambda: {"bplatz": object(), "notino": object(), "sabina": object()})
    try:
        assert ingestion_tasks._configured_store_keys() == ["bplatz"]
    finally:
        engine.dispose()


def test_refresh_raw_artifacts_are_persisted_without_an_ingestion_run(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, IngestionArtifact, Store
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'refresh-artifacts.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Store(name="Bplatz", slug="bplatz", currency="EUR", status="active"))
        session.commit()
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)

    original = b"<html><body>retailer refresh page</body></html>"
    ids = ingestion_tasks._persist_raw_artifacts("bplatz", None, [{
        "format": "html",
        "data": original,
        "content_type": "text/html",
        "source_url": "https://shop.example/item",
        "metadata": {"capture": "page_loader_body"},
    }])
    try:
        with factory() as session:
            artifact = session.scalar(select(IngestionArtifact))
            assert ids == [str(artifact.id)]
            assert artifact.raw_data == original
            assert artifact.sha256
            assert artifact.ingestion_run_id is None
    finally:
        engine.dispose()


def test_eight_hour_collection_refreshes_known_active_offers_not_discovery(tmp_path, monkeypatch):
    from decimal import Decimal
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, Offer, Store
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'eight-hour-refresh.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        active = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
        inactive = Store(name="Notino", slug="notino", currency="EUR", status="inactive")
        session.add_all([active, inactive])
        session.flush()
        session.add_all([
            Offer(store_id=active.id, external_product_id="sku-active",
                  url="https://shop.example/active", price=Decimal("49.90"),
                  currency="EUR", availability="in_stock", source="fixture",
                  status="active"),
            Offer(store_id=active.id, external_product_id="sku-disabled",
                  url="https://shop.example/disabled", price=Decimal("39.90"),
                  currency="EUR", availability="in_stock", source="fixture",
                  status="inactive"),
            Offer(store_id=inactive.id, external_product_id="sku-inactive-store",
                  url="https://shop.example/inactive", price=Decimal("29.90"),
                  currency="EUR", availability="in_stock", source="fixture",
                  status="active"),
        ])
        session.commit()

    queued = []
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(
        ingestion_tasks.refresh_price_and_stock, "apply_async",
        lambda **kwargs: queued.append(kwargs),
    )
    try:
        result = ingestion_tasks.enqueue_offer_collection_for_configured_stores()
        assert result == {"refresh_jobs_queued": 1, "stores": ["bplatz"]}
        assert queued == [{
            "kwargs": {"store_key": "bplatz", "offer_id": "sku-active"},
            "queue": "refresh",
        }]
    finally:
        engine.dispose()



def test_discovery_task_persists_original_page_bytes_and_links_them_to_staged_offer(
    tmp_path, monkeypatch
):
    import hashlib
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import UUID

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.connectors.base import OfferRecord
    from app.models import Base, IngestionArtifact, IngestionRaw, IngestionRun, Store
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'discovery-evidence.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Store(name="Bplatz", slug="bplatz", currency="EUR", status="active"))
        session.commit()

    html = b"<html><body>original fixture source bytes</body></html>"
    record = OfferRecord(
        store="bplatz",
        external_product_id="fixture-product-100",
        brand="Dior",
        fragrance="Sauvage",
        concentration="edp",
        size_ml=100,
        gtin=None,
        title="Dior Sauvage Eau de Parfum 100 ml",
        url="https://en.bplatz.de/products/fixture-product-100",
        price=Decimal("89.90"),
        currency="EUR",
        availability="in_stock",
        captured_at=datetime.now(timezone.utc).isoformat(),
        source="fixture",
    )

    class FixtureConnector:
        store_key = "bplatz"
        _raw_artifacts = [{
            "format": "html",
            "data": html,
            "content_type": "text/html",
            "source_url": record.url,
            "metadata": {"capture": "page_loader_body"},
        }]

        async def discover_products(self):
            return [{
                "externalProductId": record.external_product_id,
                "url": record.url,
                "title": record.title,
            }]

        async def fetch_offers(self, _product_key):
            return (record,)

    connector = FixtureConnector()
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "get_connector", lambda _store: connector)
    queued = []
    monkeypatch.setattr(
        ingestion_tasks.normalize_offer,
        "apply_async",
        lambda **kwargs: queued.append(kwargs),
    )

    try:
        result = ingestion_tasks.discover_store_products.run("bplatz")
        assert result["discovered"] == 1
        assert result["offers_staged"] == 1
        assert len(result["raw_ids"]) == 1
        assert len(queued) == 1

        with factory() as session:
            artifact = session.scalar(select(IngestionArtifact))
            raw = session.get(IngestionRaw, UUID(result["raw_ids"][0]))
            run = session.get(IngestionRun, artifact.ingestion_run_id)

            assert artifact.raw_data == html
            assert artifact.sha256 == hashlib.sha256(html).hexdigest()
            assert artifact.size_bytes == len(html)
            assert artifact.source_url == record.url
            assert artifact.artifact_format == "html"
            assert run is not None and run.status == "completed"
            assert raw is not None
            evidence = raw.raw_payload["_raw_evidence"]["discovery"]
            assert str(artifact.id) in evidence["raw_artifact_ids"]
            assert raw.raw_payload["externalProductId"] == record.external_product_id
    finally:
        engine.dispose()



def test_bplatz_liquid_brun_pilot_html_is_persisted_and_linked_by_celery_discovery(
    tmp_path, monkeypatch
):
    """Exercise the selected Liquid Brun parser + connector + Celery artifact path offline."""
    import asyncio
    import hashlib
    import json
    from pathlib import Path
    from uuid import UUID

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.connectors import BplatzConnector
    from app.models import Base, IngestionArtifact, IngestionRaw, IngestionRun, Store
    from app.workers import ingestion_tasks
    from scrapers.bplatz import scraper

    root = Path(__file__).resolve().parents[2]
    fixture = root / "tests" / "fixtures" / "bplatz" / "liquid-brun-54015243419916.raw.html"
    metadata = json.loads(
        (root / "tests" / "fixtures" / "bplatz" / "liquid-brun-54015243419916.meta.json")
        .read_text(encoding="utf-8")
    )
    html = fixture.read_bytes()
    url = metadata["url_final"]
    query = "French Avenue Liquid Brun"

    # Real Bplatz parser and universal connector; only transport is replaced
    # with the previously captured response bytes. No retailer request occurs.
    connector = BplatzConnector(page_loader=lambda _url, _query: html)
    loaded = asyncio.run(connector._load_page(url, query))
    assert loaded == html
    parsed = scraper.parse_product_html(loaded.decode("utf-8"), url, query)
    assert parsed is not None
    records = connector.parse_raw(parsed)
    assert len(records) == 1
    record = records[0]
    assert record.brand == "French Avenue"
    assert record.fragrance == "liquid brun"
    assert record.concentration == "edp"
    assert record.size_ml == 100
    assert record.price is not None and record.price > 0
    assert record.currency == "EUR"
    assert record.availability == "in_stock"

    async def discover_products():
        return ({
            "externalProductId": record.external_product_id,
            "url": record.url,
            "title": record.title,
        },)

    async def fetch_offers(_product_key):
        return (record,)

    connector.discover_products = discover_products
    connector.fetch_offers = fetch_offers

    engine = create_engine(f"sqlite:///{tmp_path / 'bplatz-liquid-brun-celery-artifacts.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Store(
            name="Bplatz", slug="bplatz", domain="bplatz.de",
            country="DE", currency="EUR", status="active",
        ))
        session.commit()

    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "get_connector", lambda _store: connector)
    queued = []
    monkeypatch.setattr(
        ingestion_tasks.normalize_offer,
        "apply_async",
        lambda **kwargs: queued.append(kwargs),
    )

    try:
        result = ingestion_tasks.discover_store_products.run("bplatz")
        assert result["discovered"] == 1
        assert result["offers_staged"] == 1
        assert len(queued) == 1

        with factory() as session:
            artifact = session.scalar(select(IngestionArtifact))
            raw = session.get(IngestionRaw, UUID(result["raw_ids"][0]))
            assert artifact is not None
            run = session.get(IngestionRun, artifact.ingestion_run_id)

            assert artifact.raw_data == html
            assert artifact.sha256 == hashlib.sha256(html).hexdigest()
            assert artifact.sha256 == metadata["sha256"]
            assert artifact.size_bytes == len(html)
            assert artifact.source_url == url
            assert artifact.artifact_format == "html"
            assert run is not None and run.status == "completed"
            assert raw is not None and raw.status == "pending"
            evidence = raw.raw_payload["_raw_evidence"]["discovery"]
            assert str(artifact.id) in evidence["raw_artifact_ids"]
            assert raw.raw_payload["externalProductId"] == record.external_product_id
    finally:
        engine.dispose()

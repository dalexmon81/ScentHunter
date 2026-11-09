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

def test_all_pipeline_jobs_are_registered_and_runtime_has_ten_connectors():
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
        "perfumemarket", "parfumcity", "bplatz", "orioudh", "perfumesmem",
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
    from app.models import Base, Store, StoreAuthorization
    from app.workers import ingestion_tasks
    from datetime import datetime, timezone

    engine = create_engine(f"sqlite:///{tmp_path / 'active-stores.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        active = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
        inactive = Store(name="Notino", slug="notino", currency="EUR", status="inactive")
        session.add_all([active, inactive])
        session.flush()
        session.add(StoreAuthorization(
            store_id=active.id, status="approved", collection_method="other",
            scopes=["product_discovery", "offer_data"],
            authorization_reference="fixture-written-consent",
            approved_by="isolated-test", approved_at=datetime.now(timezone.utc), terms={},
        ))
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
    from app.models import Base, IngestionArtifact, Store, StoreAuthorization
    from datetime import datetime, timezone
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'refresh-artifacts.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        store = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
        session.add(store)
        session.flush()
        session.add(StoreAuthorization(
            store_id=store.id, status="approved", collection_method="other",
            scopes=["offer_data"], authorization_reference="fixture-written-consent",
            approved_by="isolated-test", approved_at=datetime.now(timezone.utc), terms={},
        ))
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
    from app.models import Base, Offer, Store, StoreAuthorization
    from app.workers import ingestion_tasks
    from datetime import datetime, timezone

    engine = create_engine(f"sqlite:///{tmp_path / 'eight-hour-refresh.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        active = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
        inactive = Store(name="Notino", slug="notino", currency="EUR", status="inactive")
        session.add_all([active, inactive])
        session.flush()
        session.add(StoreAuthorization(
            store_id=active.id, status="approved", collection_method="other",
            scopes=["price_stock"], authorization_reference="fixture-written-consent",
            approved_by="isolated-test", approved_at=datetime.now(timezone.utc), terms={},
        ))
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



def test_reprocess_failed_offers_respects_optional_store_scope(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, IngestionRaw, Store
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'reprocess-store-scope.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        bplatz = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
        sabina = Store(name="Sabina", slug="sabina", currency="EUR", status="active")
        session.add_all([bplatz, sabina])
        session.flush()
        bplatz_raw = IngestionRaw(
            store_id=bplatz.id,
            external_product_id="bplatz-retry-1",
            raw_payload={"name": "Retry Bplatz"},
            status="rejected",
            rejection_reason="retryable:temporary_timeout",
        )
        sabina_raw = IngestionRaw(
            store_id=sabina.id,
            external_product_id="sabina-retry-1",
            raw_payload={"name": "Retry Sabina"},
            status="rejected",
            rejection_reason="retryable:temporary_timeout",
        )
        session.add_all([bplatz_raw, sabina_raw])
        session.commit()
        bplatz_id, sabina_id = str(bplatz_raw.id), str(sabina_raw.id)

    queued = []
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(
        ingestion_tasks.normalize_offer,
        "apply_async",
        lambda *, args, queue: queued.append({"args": args, "queue": queue}),
    )
    try:
        result = ingestion_tasks.reprocess_failed_offers.run(store_key="bplatz")
        assert result == {"requeued": 1, "raw_ids": [bplatz_id]}
        assert queued == [{"args": [bplatz_id], "queue": "validation"}]
        with factory() as session:
            bplatz_row = session.get(IngestionRaw, bplatz_raw.id)
            sabina_row = session.get(IngestionRaw, sabina_raw.id)
            assert bplatz_row.status == "pending"
            assert bplatz_row.rejection_reason is None
            assert sabina_row.status == "rejected"
            assert sabina_row.rejection_reason == "retryable:temporary_timeout"
    finally:
        engine.dispose()



def test_connector_quarantine_requires_consecutive_failed_runs(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, IngestionRun, Store
    from app.workers import ingestion_tasks

    engine = create_engine(f"sqlite:///{tmp_path / 'connector-quarantine.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with factory() as session:
        store = Store(name="Bplatz", slug="bplatz", currency="EUR", status="active")
        session.add(store)
        session.flush()
        session.add_all([
            IngestionRun(store_id=store.id, status="failed", started_at=now - timedelta(minutes=3)),
            IngestionRun(store_id=store.id, status="success", started_at=now - timedelta(minutes=2)),
            IngestionRun(store_id=store.id, status="failed", started_at=now - timedelta(minutes=1)),
        ])
        session.commit()

    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "QUARANTINE_AFTER", 3)
    try:
        result = ingestion_tasks.quarantine_failed_connector.run("bplatz")
        assert result["consecutive_failures"] == 1
        assert result["status"] == "active"

        with factory() as session:
            store = session.query(Store).filter_by(slug="bplatz").one()
            session.add_all([
                IngestionRun(store_id=store.id, status="failed", started_at=now + timedelta(minutes=1)),
                IngestionRun(store_id=store.id, status="failed", started_at=now + timedelta(minutes=2)),
            ])
            session.commit()

        result = ingestion_tasks.quarantine_failed_connector.run("bplatz")
        assert result["consecutive_failures"] == 3
        assert result["status"] == "quarantined"
    finally:
        engine.dispose()

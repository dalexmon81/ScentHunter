"""Production Celery Notino discovery must fail closed before any feed request."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Store, StoreAuthorization
from app.workers import ingestion_tasks


class FeedProbe:
    def __init__(self):
        self.discovery_calls = 0

    async def discover_products(self):
        self.discovery_calls += 1
        raise AssertionError("Notino feed must not be requested without authorization")


def _factory(tmp_path, scopes=None):
    engine = create_engine(f"sqlite:///{tmp_path / 'notino-auth.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        store = Store(
            name="Notino", slug="notino", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        session.add(store)
        session.flush()
        if scopes is not None:
            session.add(StoreAuthorization(
                store_id=store.id,
                status="approved",
                collection_method="affiliate_feed",
                scopes=scopes,
                authorization_reference="fixture-approval",
                evidence_url="https://affiliate.example/approval/123",
                approved_by="isolated-test",
                approved_at=datetime.now(timezone.utc),
                terms={},
            ))
        session.commit()
    return factory


@pytest.mark.parametrize(
    ("scopes", "message"),
    [
        (None, "store_collection_not_authorized:notino"),
        (["product_discovery"], "store_authorization_scope_missing:notino:offer_data"),
    ],
)
def test_notino_discovery_does_not_request_feed_without_both_required_scopes(
    monkeypatch, tmp_path, scopes, message
):
    factory = _factory(tmp_path, scopes)
    probe = FeedProbe()
    monkeypatch.setattr(ingestion_tasks, "make_session_factory", lambda: factory)
    monkeypatch.setattr(ingestion_tasks, "get_connector", lambda _key: probe)

    with pytest.raises(PermissionError, match=message):
        ingestion_tasks.discover_store_products.run("notino")

    assert probe.discovery_calls == 0
    factory.kw["bind"].dispose()



def test_legacy_notino_feed_path_checks_approval_before_fetch_and_persistence(
    monkeypatch, tmp_path
):
    from app import db as app_db
    from scrapers.notino import affiliate_feed

    factory = _factory(tmp_path)
    monkeypatch.setattr(app_db, "make_session_factory", lambda: factory)
    fetch_calls = []
    persist_calls = []
    monkeypatch.setattr(
        affiliate_feed, "_fetch_feed",
        lambda: fetch_calls.append("fetch") or b"<rss/>",
    )
    monkeypatch.setattr(
        affiliate_feed, "_persist_offers",
        lambda offers: persist_calls.append(offers) or len(offers),
    )

    with pytest.raises(affiliate_feed.FeedImportError, match="notino_feed_authorization_required"):
        affiliate_feed.import_configured_feed()
    with pytest.raises(affiliate_feed.FeedImportError, match="notino_feed_authorization_required"):
        affiliate_feed.import_feed_bytes(b"<rss/>")
    search_result = affiliate_feed.search_feed("Liquid Brun")

    assert search_result["status"] == "unavailable"
    assert search_result["error"] == "notino_feed_authorization_required"
    assert fetch_calls == []
    assert persist_calls == []
    factory.kw["bind"].dispose()


def test_legacy_notino_feed_path_accepts_current_explicit_affiliate_feed_grant(
    monkeypatch, tmp_path
):
    from app import db as app_db
    from scrapers.notino import affiliate_feed

    factory = _factory(tmp_path, ["product_discovery", "offer_data"])
    monkeypatch.setattr(app_db, "make_session_factory", lambda: factory)
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss xmlns:g="http://base.google.com/ns/1.0"><channel><item>
      <g:id>notino-liquid-brun-100</g:id>
      <g:title>French Avenue Liquid Brun Eau de Parfum 100 ml</g:title>
      <g:brand>French Avenue</g:brand>
      <g:price>29.90 EUR</g:price>
      <g:availability>in stock</g:availability>
      <g:link>https://www.notino.fr/french-avenue/liquid-brun/</g:link>
      <g:gtin>6290360375694</g:gtin>
      <g:size>100 ml</g:size>
    </item></channel></rss>"""
    fetch_calls = []
    persisted = []
    monkeypatch.setattr(
        affiliate_feed, "_fetch_feed",
        lambda: fetch_calls.append("fetch") or xml,
    )
    monkeypatch.setattr(
        affiliate_feed, "_persist_offers",
        lambda offers: persisted.extend(offers) or len(offers),
    )

    report = affiliate_feed.import_configured_feed()

    assert report["ok"] is True
    assert report["imported_offers"] == 1
    assert fetch_calls == ["fetch"]
    assert len(persisted) == 1
    assert persisted[0].gtin == "6290360375694"
    factory.kw["bind"].dispose()

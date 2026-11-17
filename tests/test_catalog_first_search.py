from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from test_bplatz_persistence_service import (
    _migrated_database, _seed_real_catalog, _create_bplatz_store, ROOT,
)
import catalog_engine
from app.api import catalog_search
from app.models import IngestionRaw, MatchAudit, Offer, ProductVariant, Store, StoreAuthorization
from app.search.catalog import _format_size_ml, catalog_status, search_catalog


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    engine, url, _ = _migrated_database(tmp_path)
    _seed_real_catalog(url)
    # This fixture explicitly represents operator-approved Bplatz collection.
    with Session(engine) as session, session.begin():
        _create_bplatz_store(session)
    fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
    meta = json.loads((fixture.parent / "liquid-brun-54015243419916.meta.json").read_text())
    item = catalog_engine.parse_product("bplatz", meta["url_final"], fixture.read_bytes())
    assert item["currency"] == "EUR" and item["currency_explicit"] is True
    monkeypatch.setenv("BPLATZ_PHASE2_PERSISTENCE", "1")
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", url)
    assert catalog_engine._maybe_persist_bplatz_phase2(item, meta["url_final"])
    with Session(engine) as session:
        offer = session.scalar(select(Offer))
        result = SimpleNamespace(offer_id=offer.id, ingestion_raw_id=offer.ingestion_raw_id,
                                 product_variant_id=offer.product_variant_id)
    yield engine, result
    engine.dispose()




def test_hydration_worker_skips_bplatz_fetch_without_collection_authorization(pilot, monkeypatch):
    engine, _result = pilot
    with Session(engine) as session, session.begin():
        store = session.scalar(select(Store).where(Store.slug == "bplatz"))
        assert store is not None
        session.execute(delete(StoreAuthorization).where(
            StoreAuthorization.store_id == store.id
        ))

    errors = []
    monkeypatch.setattr(catalog_engine, "_foreground_search_running", lambda: False)
    monkeypatch.setattr(
        catalog_engine, "_queue_mark_error",
        lambda task, detail, *args, **kwargs: errors.append(detail),
    )
    monkeypatch.setattr(
        catalog_engine, "refresh_url",
        lambda *args, **kwargs: pytest.fail("unauthorized Bplatz page must not be fetched"),
    )

    result = catalog_engine._hydrate_one_task({
        "store": "bplatz",
        "url": "https://en.bplatz.de/products/unauthorized-fixture",
        "attempts": 1,
    })
    assert result is False
    assert errors == ["store_offer_collection_not_authorized"]



def test_decimal_variant_size_display_is_stable():
    assert _format_size_ml(Decimal("100.0000")) == "100"
    assert _format_size_ml(Decimal("50.5000")) == "50.5"
    assert _format_size_ml(None) is None


def test_catalog_search_matches_fractional_variant_sizes(pilot):
    engine, result = pilot
    with Session(engine) as session, session.begin():
        base = session.get(ProductVariant, result.product_variant_id)
        assert base is not None
        session.add(ProductVariant(
            fragrance_id=base.fragrance_id,
            concentration=base.concentration,
            size_ml=Decimal("50.5"),
            is_tester=False,
            is_refill=False,
            is_gift_set=False,
            canonical_key="phase2-fractional-size-regression|50.5",
        ))
        session.flush()
        dot = search_catalog(session, "Liquid Brun 50.5 ml")
        comma = search_catalog(session, "Liquid Brun 50,5 ml")
        assert dot["count"] == 1 and dot["results"][0]["name"].endswith("50.5 ml")
        assert comma["count"] == 1 and comma["results"][0]["name"].endswith("50.5 ml")


def test_fixture_to_catalog_api_without_network(pilot, monkeypatch):
    engine, result = pilot
    monkeypatch.setattr(catalog_search, "_engine", lambda: engine)
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *args, **kwargs: pytest.fail("search called a store"))
    app = FastAPI()
    app.include_router(catalog_search.router)
    with TestClient(app) as client:
        response = client.get("/api/catalog/search", params={"q": "French Avenue Liquid Brun EDP 100ml"})
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == data["offer_count"] == 1
        item = data["results"][0]
        assert item["catalog_id"] == str(result.product_variant_id)
        assert item["name"] == "Liquid Brun Eau de Parfum 100 ml"
        offer = item["offers"][0]
        assert offer["store"] == "Bplatz"
        assert offer["availability"] == "in_stock"
        assert offer["currency"] == "EUR"
        assert Decimal(offer["price"]) > 0
        assert offer["url"].startswith("https://bplatz.de/products/")
        assert datetime.fromisoformat(offer["captured_at"]).tzinfo is not None
        assert offer["shipping_cost"] is None
        status = client.get("/api/catalog/status").json()
        assert status["status"] == "ready"
        assert status["canonical_variants"] >= 1
        assert status["published_offers"] == 1
        assert status["offers_by_store"]["bplatz"] == 1
        assert status["latest_offer_update_by_store"]["bplatz"] == offer["captured_at"]
        assert status["freshness_window_hours"] == 24

        other = client.get("/api/catalog/search", params={"q": "Liquid Brun 150 ml"}).json()
        assert other["count"] == 1 and other["offer_count"] == 0
        assert "Limited Edition" in other["results"][0]["name"]
        assert client.get("/api/catalog/search", params={"q": "no-such-perfume"}).json()["count"] == 0
        assert client.get("/api/catalog/search", params={"q": "9" * 100}).json()["count"] == 0
        assert client.get("/api/catalog/search", params={"q": "Liquid Brun tester"}).json()["count"] == 0
        assert client.get("/api/catalog/search", params={"q": "Liquid Brun refill"}).json()["count"] == 0
        assert client.get("/api/catalog/search", params={"q": "Liquid Brun gift set"}).json()["count"] == 0


def test_missing_catalog_returns_503_without_creating_database(tmp_path, monkeypatch):
    database = tmp_path / "missing" / "catalog.sqlite3"
    monkeypatch.setenv("SCENTHUNTER_CATALOG_DATABASE_URL", f"sqlite:///{database}")
    catalog_search._engine.cache_clear()
    app = FastAPI()
    app.include_router(catalog_search.router)
    with TestClient(app) as client:
        assert client.get("/api/catalog/search", params={"q": "Liquid Brun"}).status_code == 503
    assert not database.parent.exists()


def test_search_route_is_registered_on_production_app():
    import main

    paths = {route.path for route in main.app.routes}
    assert "/api/catalog/search" in paths
    assert "/api/catalog/status" in paths


def test_publication_gate_and_freshness(pilot):
    engine, result = pilot
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        offer = session.get(Offer, result.offer_id)
        store = session.get(Store, offer.store_id)
        raw = session.get(IngestionRaw, result.ingestion_raw_id)
        audit = session.scalar(select(MatchAudit).where(MatchAudit.offer_id == offer.id))

        def count():
            return search_catalog(session, "Liquid Brun 100ml", now=now)["offer_count"]

        assert count() == 1
        payload = dict(raw.raw_payload)
        raw.raw_payload = {**payload, "currency_explicit": False}
        session.flush()
        assert count() == 0
        raw.raw_payload = payload
        session.flush()
        for obj, field, invalid in (
            (offer, "captured_at", now - timedelta(hours=25)),
            (offer, "captured_at", now + timedelta(minutes=1)),
            (offer, "valid_until", now - timedelta(seconds=1)),
            (offer, "availability", "out_of_stock"),
            (offer, "price", Decimal("0")),
            (offer, "currency", "USD"),
            (offer, "url", "https://bplatz.de.evil.test/product"),
            (offer, "url", "https://user@bplatz.de/product"),
            (offer, "url", "http://bplatz.de/product"),
            (offer, "url", "https://bplatz.de:80/product"),
            (offer, "url", "https://bplatz.de:444/product"),
            (offer, "status", "rejected"),
            (store, "status", "inactive"),
            (store, "domain", None),
            (raw, "status", "matched"),
            (audit, "product_variant_id", None),
        ):
            original = getattr(obj, field)
            setattr(obj, field, invalid)
            session.flush()
            assert count() == 0, field
            setattr(obj, field, original)
            session.flush()
        assert count() == 1


def test_missing_structured_currency_is_not_explicit():
    html = b'''<h1>French Avenue Liquid Brun 100 ml</h1>
    <script type="application/ld+json">{"@type":"Product",
      "name":"French Avenue Liquid Brun 100 ml",
      "offers":{"@type":"Offer","price":"25","availability":"https://schema.org/InStock"}}
    </script>'''
    item = catalog_engine.parse_product("bplatz", "https://bplatz.de/products/example", html)
    assert item["currency"] == "EUR"
    assert item["currency_explicit"] is False

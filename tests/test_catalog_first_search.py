from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from urllib.parse import quote

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_bplatz_persistence_service import (
    _migrated_database, _seed_real_catalog, ROOT,
)
import catalog_engine
from app.api import catalog_search
from app.models import IngestionRaw, MatchAudit, Offer, Store
from app.search.catalog import catalog_status, search_catalog, _display_offer_url
from scrapers.notino.affiliate_feed import validated_cj_offer_url


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    engine, url, _ = _migrated_database(tmp_path)
    _seed_real_catalog(url)
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


def test_fixture_to_catalog_api_without_network(pilot, monkeypatch):
    engine, result = pilot
    monkeypatch.setattr(catalog_search, "_engine", lambda: engine)
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *args, **kwargs: pytest.fail("search called a store"))
    app = FastAPI()
    app.include_router(catalog_search.router)
    with TestClient(app) as client:
        response = client.get("/api/catalog/search", params={"q": "French Avenue Liquid Brun EDP 100ml"})
        public_response = client.get("/search", params={"q": "French Avenue Liquid Brun EDP 100ml"})
        assert public_response.status_code == 200
        public_data = public_response.json()
        assert public_data["count"] == public_data["offer_count"] == 1
        assert public_data["results"][0]["offers"][0]["store"] == "Bplatz"
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
        assert offer["product_url"] == offer["url"]
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
        assert client.get("/api/catalog/search", params={"q": "Liquid Brun mini"}).json()["count"] == 0


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
    assert "/search" in paths
    assert "/api/catalog/status" in paths
    public_search_routes = [route for route in main.app.routes if route.path == "/search"]
    assert public_search_routes[0].endpoint.__module__ == "app.api.catalog_search"


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


def test_bplatz_catalog_parser_preserves_explicit_title_size_and_concentration():
    html = b'''<h1>French Avenue Liquid Brun Eau de Parfum 100 ml</h1>
    <script type="application/ld+json">{"@type":"Product",
      "name":"French Avenue Liquid Brun Eau de Parfum 100 ml",
      "brand":{"@type":"Brand","name":"French Avenue"},
      "offers":{"@type":"Offer","price":"25","priceCurrency":"EUR",
      "availability":"https://schema.org/InStock"}}
    </script>'''
    item = catalog_engine.parse_product(
        "bplatz", "https://en.bplatz.de/products/liquid-brun", html
    )
    assert item is not None
    assert item["size_ml"] == 100
    assert item["concentration"] == "Eau de Parfum"


def test_bplatz_hydration_uses_authoritative_parser_for_size_and_currency_evidence():
    fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
    meta = json.loads(
        (fixture.parent / "liquid-brun-54015243419916.meta.json").read_text()
    )
    item = catalog_engine._secondary_store_parser(
        "bplatz", meta["url_final"], meta["url_final"],
        html_data=fixture.read_bytes(),
    )
    assert item is not None
    assert item["size_ml"] == 100
    assert item["currency"] == "EUR"
    assert item["currency_explicit"] is True
    assert item["sku"] == "6290360375694"
    assert item["gtin"] == "6290360375694"
    assert item["availability"] == "in_stock"

    record = {
        "raw_name": item["name"],
        "brand_raw": item["brand"],
        "size_ml": item["size_ml"],
        "price": item["price_num"],
        "currency": item["currency"],
        "currency_explicit": item["currency_explicit"],
        "product_url": item["url"],
        "availability": item["availability"],
        "sku": item["sku"],
        "gtin": item["gtin"],
    }
    from scenthunter_next_engine.next_engine_service import NextEngineService
    matcher = NextEngineService.from_catalog_file(ROOT / "backend/product_catalog.json")
    matched = matcher.process_records(
        [record], retailer="Bplatz", currency_default="EUR",
    ).aggregation
    assert matched.matched_offer_count == 1
    assert matched.groups[0].canonical_product_id == "SH-0030"
    assert matched.groups[0].canonical_variant_id == "VAR-f87146c82d167f4c"


def test_missing_structured_currency_is_not_explicit():
    html = b'''<h1>French Avenue Liquid Brun 100 ml</h1>
    <script type="application/ld+json">{"@type":"Product",
      "name":"French Avenue Liquid Brun 100 ml",
      "offers":{"@type":"Offer","price":"25","availability":"https://schema.org/InStock"}}
    </script>'''
    item = catalog_engine.parse_product("bplatz", "https://bplatz.de/products/example", html)
    assert item["currency"] == "EUR"
    assert item["currency_explicit"] is False


def test_browser_demo_route_is_registered_and_uses_catalog_api():
    app = FastAPI()
    app.include_router(catalog_search.router)
    with TestClient(app) as client:
        response = client.get("/catalog-demo")
        assert response.status_code == 200
        assert "ScentHunter" in response.text
        assert "/api/catalog/status" in response.text
        assert "/api/catalog/search?q=" in response.text
        assert "Nessuno store viene interrogato durante la ricerca" in response.text



def test_notino_catalog_link_preserves_only_exact_validated_cj_destination():
    product_url = "https://www.notino.fr/french-avenue/liquid-brun/"
    click_url = (
        "https://anrdoezrs.net/click-123-456?url="
        + quote(product_url, safe="")
    )
    assert validated_cj_offer_url(click_url, product_url) == click_url

    offer = SimpleNamespace(url=product_url)
    raw = SimpleNamespace(raw_payload={"affiliate_url": click_url})
    for slug in ("notino", "notino-fr"):
        store = SimpleNamespace(slug=slug)
        assert _display_offer_url(offer, store, raw) == click_url

    wrong_destination = click_url.replace("liquid-brun", "other-product")
    raw.raw_payload = {"affiliate_url": wrong_destination}
    assert _display_offer_url(offer, store, raw) == product_url

    raw.raw_payload = {
        "affiliate_url": "https://evil.example/click?url=" + quote(product_url, safe="")
    }
    assert _display_offer_url(offer, store, raw) == product_url



def test_notino_affiliate_link_is_returned_by_catalog_search_api(pilot, monkeypatch):
    engine, result = pilot
    product_url = "https://www.notino.fr/french-avenue/liquid-brun/"
    click_url = (
        "https://anrdoezrs.net/click-123-456?url="
        + quote(product_url, safe="")
    )
    with Session(engine) as session:
        offer = session.get(Offer, result.offer_id)
        store = session.get(Store, offer.store_id)
        raw = session.get(IngestionRaw, result.ingestion_raw_id)
        store.slug = "notino-fr"
        store.name = "Notino.fr"
        store.domain = "www.notino.fr"
        offer.url = product_url
        raw.raw_payload = {
            **dict(raw.raw_payload),
            "currency_explicit": True,
            "affiliate_url": click_url,
        }
        session.commit()

    monkeypatch.setattr(catalog_search, "_engine", lambda: engine)
    app = FastAPI()
    app.include_router(catalog_search.router)
    with TestClient(app) as client:
        response = client.get(
            "/api/catalog/search",
            params={"q": "French Avenue Liquid Brun EDP 100ml"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["offer_count"] == 1
    returned_offer = data["results"][0]["offers"][0]
    assert returned_offer["url"] == click_url
    assert returned_offer["product_url"] == product_url


def test_bplatz_hydration_uses_authoritative_parser_for_size_and_currency():
    fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
    meta = json.loads(
        (fixture.parent / "liquid-brun-54015243419916.meta.json").read_text()
    )
    html = fixture.read_bytes()
    item = catalog_engine._secondary_store_parser(
        "bplatz", meta["url_final"], meta["url_final"], html_data=html,
    )
    assert item is not None
    assert item["size_ml"] == 100
    assert item["currency"] == "EUR"
    assert item["currency_explicit"] is True
    assert item["sku"] == "6290360375694"
    assert item["gtin"] == "6290360375694"
    assert item["availability"] == "in_stock"


def test_reviewed_bplatz_gtin_supplement_resolves_only_exact_verified_variants():
    from scenthunter_next_engine.next_engine_service import NextEngineService

    matcher = NextEngineService.from_catalog_file(ROOT / "backend/product_catalog.json")
    cases = [
        {
            "raw_name": "Lattafa Parfum Mayar Natural Intense Eau de Parfum 100ml",
            "brand_raw": "Lattafa", "size_ml": 100, "gtin": "6290360598970",
            "price": 24.50, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-mayar",
            "availability": "in_stock",
        },
        {
            "raw_name": "Niche Emarati Perfume Lujain Eau de Parfum 100ml",
            "brand_raw": "Niche Emarati", "size_ml": 100, "gtin": "6290360592169",
            "price": 33.19, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-lujain",
            "availability": "in_stock",
        },
        {
            "raw_name": "Maison Alhambra Pink Velvet Eau de Parfum 80 ML (XL)",
            "brand_raw": "Maison Alhambra", "size_ml": 80, "gtin": "6291108735749",
            "price": 17.68, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-pink-velvet",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone 1849 Matador Green Valley Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906593",
            "price": 11.50, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-green-valley",
            "availability": "in_stock",
        },
        {
            "raw_name": "Maison Alhambra Salvo Eau de Parfum 100ml",
            "brand_raw": "Maison Alhambra", "size_ml": 100, "gtin": "6291107459363",
            "price": 17.68, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-salvo",
            "availability": "in_stock",
        },
        {
            "raw_name": "Emper Shelton Ilang 62 Eau de Parfum 100ml",
            "brand_raw": "Emper", "size_ml": 100, "gtin": "6291108529171",
            "price": 15.99, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-ilang",
            "availability": "in_stock",
        },
        {
            "raw_name": "Emper Shelton Velvetier 42 Eau de Parfum 100ml",
            "brand_raw": "Emper", "size_ml": 100, "gtin": "6291108529188",
            "price": 8.65, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-velvetier",
            "availability": "in_stock",
        },
        {
            "raw_name": "Emper Shelton Noir 92 Eau de Parfum 100ml",
            "brand_raw": "Emper", "size_ml": 100, "gtin": "6291108529164",
            "price": 8.65, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-noir",
            "availability": "in_stock",
        },
        {
            "raw_name": "Al Fares Asrar Al Layl Eau de Parfum 100 ml",
            "brand_raw": "Al Fares", "size_ml": 100, "gtin": "6294021906241",
            "price": 19.89, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-asrar",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Coastal Waves Pistacia Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906784",
            "price": 9.98, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-pistacia",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Coastal Waves Rose Couture Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906777",
            "price": 11.48, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-rose-couture",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Blast Night Version Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021907026",
            "price": 11.50, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-blast-night",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Hayati Lychee Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021904759",
            "price": 11.50, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/example-hayati-lychee",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Hayati Marshmallow Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021904742",
            "price": 11.49, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-hayati-marshmallow",
            "availability": "in_stock",
        },
        {
            "raw_name": "Al Fares Hajes Flame Eau de Parfum 100 ml",
            "brand_raw": "Al Fares", "size_ml": 100, "gtin": "6294021907668",
            "price": 17.89, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-hajes-flame",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Perfume Blast Infrared Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021907019",
            "price": 11.50, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-blast-infrared",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Perfume Blast Confident Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021907002",
            "price": 8.50, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-blast-confident",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Alvina Desira Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906661",
            "price": 14.49, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-alvina-desira",
            "availability": "in_stock",
        },
        {
            "raw_name": "Ard Al Zaafaran Perfume Thara Al Oud Eau de Parfum 100ml",
            "brand_raw": "Ard Al Zaafaran", "size_ml": 100, "gtin": "6435074242867",
            "price": 14.18, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-thara-al-oud",
            "availability": "in_stock",
        },
        {
            "raw_name": "Chic Velvet Vert Secret Eau de Parfum 100ml",
            "brand_raw": "Maison Alhambra", "size_ml": 100, "gtin": "6290360590707",
            "price": 17.68, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-chic-velvet",
            "availability": "in_stock",
        },
        {
            "raw_name": "Lattafa Perfume Very Eau de Parfum 100ml",
            "brand_raw": "Lattafa", "size_ml": 100, "gtin": "6290360599090",
            "price": 27.80, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-lattafa-sehr",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone 1849 Matador Velarus Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906586",
            "price": 11.49, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-matador-velarus",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone 1849 Matador Linton Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906579",
            "price": 11.49, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-matador-linton",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Coastal Waves Aqua Marine Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021906760",
            "price": 9.98, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-coastal-waves-aqua-marine",
            "availability": "in_stock",
        },
        {
            "raw_name": "Al Fars Ward Al Qamr Eau de Parfum 100 ml",
            "brand_raw": "Al Fares", "size_ml": 100, "gtin": "6294021906234",
            "price": 16.89, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-ward-al-qamr",
            "availability": "in_stock",
        },
        {
            "raw_name": "Ard Al Zaafaran Perfume Al Sayaad For Men Eau de Parfum 100 ml",
            "brand_raw": "Ard Al Zaafaran", "size_ml": 100, "gtin": "6423080615355",
            "price": 14.99, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-al-sayaad",
            "availability": "in_stock",
        },
        {
            "raw_name": "Al Fares Layaali Eau de Parfum 100ml",
            "brand_raw": "Al Fares", "size_ml": 100, "gtin": "6291108522431",
            "price": 9.99, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-layaali",
            "availability": "in_stock",
        },
        {
            "raw_name": "Milestone Obsession Cherry Overdose Eau de Parfum 100 ml",
            "brand_raw": "Milestone", "size_ml": 100, "gtin": "6294021905442",
            "price": 9.98, "currency": "EUR", "currency_explicit": True,
            "product_url": "https://en.bplatz.de/products/test-cherry-overdose",
            "availability": "in_stock",
        },
    ]
    from scenthunter_next_engine.canonical_matcher import _offer_gtin
    from scenthunter_next_engine.offer_normalizer import normalize_offer
    for case in cases:
        probe = normalize_offer(case, retailer="Bplatz", currency_default="EUR")
        gtin = _offer_gtin(probe.raw_payload)
        assert gtin in matcher._matcher._gtin_registry, f"GTIN missing from registry: {gtin}"
        verified = matcher._matcher._match_verified_gtin(probe)
        assert verified is not None and verified.reason == "verified_gtin_exact_variant", (
            gtin, verified,
        )

    result = matcher.process_records(
        cases, retailer="Bplatz", currency_default="EUR",
    ).aggregation
    assert result.matched_offer_count == 28, [(item.offer.raw_name, item.reason, item.candidate_product_ids) for item in result.unresolved]
    expected_gtins = {
        "6290360598970", "6290360592169", "6291108735749",
        "6294021906593", "6291107459363", "6291108529171",
        "6291108529188", "6291108529164", "6294021906241",
        "6294021906784", "6294021906777", "6294021907026",
        "6294021904759", "6294021904742", "6294021907668",
        "6294021907019", "6294021907002", "6294021906661",
        "6435074242867", "6290360590707", "6290360599090",
        "6294021906586", "6294021906579", "6294021906760",
        "6294021906234", "6423080615355", "6291108522431",
        "6294021905442",
    }
    assert {group.canonical_product_id for group in result.groups} == {
        "SH-BPLATZ-" + gtin for gtin in expected_gtins
    }
    assert {group.canonical_variant_id for group in result.groups} == {
        "VAR-BPLATZ-" + gtin for gtin in expected_gtins
    }

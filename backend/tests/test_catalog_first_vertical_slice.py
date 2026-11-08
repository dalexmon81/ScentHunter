"""PostgreSQL-backed offline proof of the catalog-first offer lifecycle.

The XML is an in-test fixture. This test never calls Notino or any retailer.
The workflow provisions a disposable PostgreSQL database and seeds the
canonical catalog before running this test.
"""
from decimal import Decimal
from dataclasses import replace
import json
from pathlib import Path

from sqlalchemy import select

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.legacy_catalog import router as legacy_catalog_router
from app.api.catalog_search import router as catalog_search_router
from app.connectors.notino import NotinoAffiliateFeedConnector
from app.connectors.bplatz import BplatzConnector
from app.db import make_engine
from app.matching.offer_matcher import match_staged_offer
from app.services.product_normalization import normalize_product
from app.workers.offer_promotion import promote_matched_offers
from scrapers.bplatz.scraper import parse_product_html
from app.models import (
    IngestionRaw,
    LegacyProductIdMap,
    MatchAudit,
    Offer,
    PriceHistory,
    ProductVariant,
    Store,
)
from app.services.ingestion_persistence import promote_offer
from app.workers.connector_ingestion import run_connector_once
from sqlalchemy.orm import sessionmaker


NOTINO_XML_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:g="http://base.google.com/ns/1.0"><channel><item>
  <g:id>notino-dior-sauvage-edp-100-fixture</g:id>
  <g:title>Dior Sauvage Eau de Parfum 100 ml</g:title>
  <g:brand>Dior</g:brand>
  <g:price>99.90 EUR</g:price>
  <g:availability>in stock</g:availability>
  <g:link>https://www.notino.fr/dior/sauvage-eau-de-parfum/</g:link>
  <g:size>100 ml</g:size>
</item></channel></rss>"""

LEGACY_PRODUCT_ID = "SH-AUTO-0178"
CANONICAL_KEY = "christian-dior|sauvage|edp|100|standard"


def test_fixture_offer_flows_through_postgres_to_catalog_api():
    engine = make_engine()
    assert engine.dialect.name == "postgresql", (
        "This integration test must run against PostgreSQL, not SQLite"
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    try:
        with factory() as session:
            variant = session.scalar(
                select(ProductVariant).where(
                    ProductVariant.canonical_key == CANONICAL_KEY
                )
            )
            assert variant is not None, "seeded Dior Sauvage EDP 100 ml variant missing"
            product_map = session.get(LegacyProductIdMap, LEGACY_PRODUCT_ID)
            assert product_map is not None, "seeded legacy product mapping missing"

            store = session.scalar(select(Store).where(Store.slug == "notino"))
            if store is None:
                store = Store(
                    name="Notino",
                    slug="notino",
                    domain="notino.fr",
                    country="FR",
                    currency="EUR",
                    offer_ttl_minutes=1440,
                    status="active",
                )
                session.add(store)
                session.flush()
            # Keep this disposable test deterministic: the six-day-old fixture
            # must exceed the configured one-day freshness window.
            store.offer_ttl_minutes = 1440
            assert store.status == "active"
            session.commit()

        connector = NotinoAffiliateFeedConnector(
            feed_loader=lambda: NOTINO_XML_FIXTURE
        )
        result = run_connector_once(connector, factory)
        assert result == {
            "store": "notino",
            "status": "completed",
            "discovered": 1,
            "staged": 1,
            "rejected": 0,
            "published": 0,
        }
        assert connector.raw_evidence_for() == NOTINO_XML_FIXTURE

        with factory() as session:
            raw = session.scalar(
                select(IngestionRaw).where(
                    IngestionRaw.external_product_id
                    == "notino-dior-sauvage-edp-100-fixture"
                )
            )
            assert raw is not None
            assert raw.status == "pending"

            decision = match_staged_offer(session, raw.id)
            assert decision.status == "matched"
            assert decision.method == "canonical_key_exact"
            assert decision.product_variant_id == variant.id

            offer_id = promote_offer(
                session,
                ingestion_raw_id=raw.id,
                price=Decimal("99.90"),
                currency="EUR",
                url="https://www.notino.fr/dior/sauvage-eau-de-parfum/",
                availability="in_stock",
                source="authorized_affiliate_xml_fixture",
                confidence=decision.confidence,
            )
            session.commit()

            offer = session.get(Offer, offer_id)
            assert offer is not None
            assert offer.status == "active"
            assert offer.product_variant_id == variant.id
            assert offer.price == Decimal("99.90")
            assert offer.currency == "EUR"
            assert offer.availability == "in_stock"
            assert raw.status == "promoted"
            assert len(list(session.scalars(
                select(PriceHistory).where(PriceHistory.offer_id == offer_id)
            ))) == 1
            assert len(list(session.scalars(
                select(MatchAudit).where(MatchAudit.offer_id == offer_id)
            ))) == 1

        # Exercise the actual HTTP route used by the catalog API.
        api = FastAPI()
        api.include_router(legacy_catalog_router)
        with TestClient(api) as client:
            http_response = client.get(
                f"/catalog/legacy-products/{LEGACY_PRODUCT_ID}/offers"
            )
        assert http_response.status_code == 200, http_response.text
        response = http_response.json()
        assert response["legacy_product_id"] == LEGACY_PRODUCT_ID
        notino_offers = [offer for offer in response["offers"] if offer["store"] == "notino"]
        assert len(notino_offers) == 1
        api_offer = notino_offers[0]
        assert api_offer["phase2_offer_id"] == str(offer_id)
        assert api_offer["store"] == "notino"
        assert api_offer["price"] == 99.9
        assert api_offer["currency"] == "EUR"
        assert api_offer["availability"] == "in_stock"
        assert api_offer["size_ml"] == 100
        assert api_offer["url"] == (
            "https://www.notino.fr/dior/sauvage-eau-de-parfum/"
        )

        # The same persisted offer must also be visible through the new
        # catalog-first search route used by the frontend migration.
        search_api = FastAPI()
        search_api.include_router(catalog_search_router)
        with TestClient(search_api) as client:
            search_response = client.get(
                "/catalog/search", params={"q": "Sauvage"}
            )
        assert search_response.status_code == 200, search_response.text
        search_payload = search_response.json()
        product = next(
            row for row in search_payload["results"]
            if row["brand"].lower() == "dior"
            and row["fragrance"].lower() == "sauvage"
        )
        published_offers = [
            offer
            for variant_row in product["variants"]
            for offer in variant_row["offers"]
        ]
        notino_published_offers = [offer for offer in published_offers if offer["store"] == "notino"]
        assert len(notino_published_offers) == 1, published_offers
        assert notino_published_offers[0]["price"] == 99.9
        assert notino_published_offers[0]["currency"] == "EUR"
        assert notino_published_offers[0]["availability"] == "in_stock"
        assert notino_published_offers[0]["url"] == (
            "https://www.notino.fr/dior/sauvage-eau-de-parfum/"
        )
    finally:
        engine.dispose()



def test_bplatz_liquid_brun_fixture_matches_canonical_variant_but_stale_capture_is_not_published():
    """Use authentic Bplatz HTML and the production parser; never assign a variant by hand."""
    root = Path(__file__).resolve().parents[2]
    fixture_path = root / "tests" / "fixtures" / "bplatz" / "liquid-brun-54015243419916.raw.html"
    meta_path = root / "tests" / "fixtures" / "bplatz" / "liquid-brun-54015243419916.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    html = fixture_path.read_text(encoding="utf-8")
    parsed = parse_product_html(html, meta["url_final"], "French Avenue Liquid Brun")

    assert parsed is not None
    assert parsed["brand"] == "French Avenue"
    assert parsed["size_ml"] == 100
    assert parsed["concentration"] == "Eau de Parfum"
    assert parsed["sku"] == "6290360375694"
    assert parsed["gtin"] == "6290360375694"

    connector = BplatzConnector()
    records = connector.parse_raw(parsed)
    assert len(records) == 1
    # Preserve the source capture time from the fixture metadata. Do not replace
    # it with test execution time: the observation is several days old.
    record = replace(
        records[0],
        external_product_id=meta["shopify_variant_id"],
        captured_at=meta["acquired_at_utc"],
    )
    assert record.price is not None and record.price > 0
    assert record.currency == "EUR"
    assert record.availability == "in_stock"

    identity = normalize_product(
        record.brand, record.title,
        concentration=record.concentration,
        size_ml=record.size_ml,
    )
    assert identity.canonical_key == "french-avenue|liquid-brun|edp|100|standard"

    engine = make_engine()
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            variant = session.scalar(
                select(ProductVariant).where(
                    ProductVariant.canonical_key == identity.canonical_key
                )
            )
            assert variant is not None, "seeded French Avenue Liquid Brun EDP 100 ml variant missing"
            store = session.scalar(select(Store).where(Store.slug == "bplatz"))
            # This is an isolated CI database. Provisioning the retailer row here
            # does not activate a production connector or write to staging.
            if store is None:
                store = Store(
                    name="Bplatz",
                    slug="bplatz",
                    domain="bplatz.de",
                    country="DE",
                    currency="EUR",
                    status="active",
                )
                session.add(store)
                session.flush()
            assert store.status == "active"
            # The six-day-old fixture must exceed this one-day freshness window.
            store.offer_ttl_minutes = 1440
            raw_payload = record.to_dict()
            raw_payload["_source_fixture"] = {
                "url": meta["url_final"],
                "acquired_at_utc": meta["acquired_at_utc"],
                "sha256": meta["sha256"],
                "fixture_path": str(fixture_path.relative_to(root)),
            }
            raw = IngestionRaw(
                store_id=store.id,
                external_product_id=record.external_product_id,
                raw_payload=raw_payload,
                status="pending",
            )
            session.add(raw)
            session.flush()

            decision = match_staged_offer(session, raw.id)
            assert decision.status == "matched"
            assert decision.method in {
                "gtin_exact", "canonical_key_exact", "normalized_attributes_exact"
            }
            assert decision.product_variant_id == variant.id
            session.commit()
            raw_id = raw.id
            store_id = store.id

        # The real publication worker must reject this six-day-old capture.
        # A successful parser + match is not enough to make stale pricing live.
        assert promote_matched_offers(factory) == {
            "processed": 1, "published": 0, "blocked": 1,
        }

        with factory() as session:
            raw = session.get(IngestionRaw, raw_id)
            assert raw.status == "matched"
            assert raw.rejection_reason == "promotion_blocked:source_capture_expired"
            assert session.scalar(
                select(Offer).where(
                    Offer.store_id == store_id,
                    Offer.external_product_id == meta["shopify_variant_id"],
                )
            ) is None
            assert session.scalars(
                select(PriceHistory)
                .join(Offer, PriceHistory.offer_id == Offer.id)
                .where(
                    Offer.store_id == store_id,
                    Offer.external_product_id == meta["shopify_variant_id"],
                )
            ).all() == []

        # Catalog search may return the identity, but must not surface the stale
        # fixture as a purchasable offer.
        api = FastAPI()
        api.include_router(catalog_search_router)
        with TestClient(api) as client:
            response = client.get("/catalog/search", params={"q": "Liquid Brun"})
        assert response.status_code == 200, response.text
        payload = response.json()
        product = next(
            row for row in payload["results"]
            if row["brand"].lower() == "french avenue"
            and row["fragrance"].lower() == "liquid brun"
        )
        matching_variant = next(
            row for row in product["variants"]
            if row["canonical_key"] == identity.canonical_key
        )
        assert matching_variant["offers"] == []
    finally:
        engine.dispose()

"""PostgreSQL-backed offline proof of the catalog-first offer lifecycle.

The XML is an in-test fixture. This test never calls Notino or any retailer.
The workflow provisions a disposable PostgreSQL database and seeds the
canonical catalog before running this test.
"""
from decimal import Decimal

from sqlalchemy import select

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.legacy_catalog import router as legacy_catalog_router
from app.api.catalog_search import router as catalog_search_router
from app.connectors.notino import NotinoAffiliateFeedConnector
from app.db import make_engine
from app.matching.offer_matcher import match_staged_offer
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
                    status="active",
                )
                session.add(store)
                session.flush()
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
        assert len(response["offers"]) == 1
        api_offer = response["offers"][0]
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
        assert len(published_offers) == 1, published_offers
        assert published_offers[0]["store"] == "notino"
        assert published_offers[0]["price"] == 99.9
        assert published_offers[0]["currency"] == "EUR"
        assert published_offers[0]["availability"] == "in_stock"
        assert published_offers[0]["url"] == (
            "https://www.notino.fr/dior/sauvage-eau-de-parfum/"
        )
    finally:
        engine.dispose()

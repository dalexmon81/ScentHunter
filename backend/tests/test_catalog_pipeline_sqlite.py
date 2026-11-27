from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.connectors.base import StoreConnector
from app.models import (
    Base, Brand, Fragrance, IngestionRaw, MatchAudit, Offer,
    PriceHistory, ProductVariant, Store,
)
from app.offers.ingestion import persist_connector_record
from app.pricing.offer_refresh import refresh_offer_observation
from app.search.catalog import search_catalog


class FixtureRetailerConnector(StoreConnector):
    store_key = "deloox"

    async def discover_products(self, *, cursor=None, limit=100):
        return ()

    async def fetch_product(self, external_product_id):
        return None

    async def fetch_offers(self, product_key):
        return ()

    async def fetch_price_and_stock(self, offer_id):
        raise LookupError("fixture has no remote refresh")

    def parse_raw(self, raw):
        return dict(raw)


def test_catalog_first_pipeline_promotes_searches_and_refreshes_without_network_or_neon():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    connector = FixtureRetailerConnector()
    store_id = uuid4()
    variant_id = uuid4()
    record = {
        "external_product_id": "DELOOX-FIXTURE-123",
        "raw_name": "Dior Sauvage Eau de Parfum 100 ml",
        "brand_raw": "Dior",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "price": "89.90",
        "currency": "EUR",
        "currency_explicit": True,
        "availability": "in_stock",
        "product_url": "https://www.deloox.be/produit/123/dior-sauvage-eau-de-parfum-100-ml.html",
        "source": "deloox_fixture",
    }

    try:
        with Session(engine) as session, session.begin():
            store = Store(
                id=store_id, name="Deloox.be", slug="deloox-be",
                domain="www.deloox.be", country="BE", currency="EUR",
                status="active",
            )
            brand = Brand(
                name="Dior", slug="dior", normalized_name="dior",
            )
            session.add_all([store, brand])
            session.flush()
            fragrance = Fragrance(
                brand_id=brand.id, name="Sauvage", slug="sauvage",
            )
            session.add(fragrance)
            session.flush()
            variant = ProductVariant(
                id=variant_id, fragrance_id=fragrance.id,
                concentration="Eau de Parfum", size_ml=100,
                is_tester=False, is_refill=False,
                is_gift_set=False, is_mini=False,
                canonical_key="dior|sauvage|edp|100|regular",
            )
            session.add(variant)
            session.flush()

            result = persist_connector_record(
                session, connector=connector, store_id=store_id,
                raw_record=dict(record), matcher=None,
            )
            assert result.status == "promoted", result.reason
            assert result.offer_id is not None
            assert result.product_variant_id == variant_id

        with Session(engine) as session:
            offer = session.get(Offer, result.offer_id)
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            assert offer is not None and offer.status == "active"
            assert raw is not None and raw.status == "promoted"
            assert raw.product_variant_id == variant_id
            assert session.scalar(select(func.count()).select_from(MatchAudit)) == 1
            first = search_catalog(
                session, "Dior Sauvage EDP 100ml",
            )
            assert first["count"] == 1
            assert first["offer_count"] == 1
            visible = first["results"][0]["offers"][0]
            assert visible["store"] == "Deloox.be"
            assert visible["price"] == "89.90"
            assert visible["currency"] == "EUR"
            assert visible["url"] == record["product_url"]

        with Session(engine) as session, session.begin():
            refreshed = refresh_offer_observation(
                session, offer_id=result.offer_id,
                observation={
                    "price": "79.90", "currency": "EUR",
                    "availability": "out_of_stock",
                    "product_url": record["product_url"],
                },
                source="deloox_fixture_refresh", currency_explicit=True,
            )
            assert refreshed == result.offer_id

        with Session(engine) as session:
            updated = search_catalog(
                session, "Dior Sauvage EDP 100ml",
            )
            assert updated["count"] == 1
            # Out-of-stock offers remain visible with their explicit stock state.
            assert updated["offer_count"] == 1
            assert updated["results"][0]["offers"][0]["availability"] == "out_of_stock"
            assert session.scalar(select(func.count()).select_from(Offer)) == 1
            assert session.scalar(select(func.count()).select_from(PriceHistory)) == 2
            offer = session.get(Offer, result.offer_id)
            assert offer.price == Decimal("79.90")
            assert offer.availability == "out_of_stock"
            assert offer.product_variant_id == variant_id
    finally:
        engine.dispose()

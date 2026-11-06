"""PostgreSQL integration tests for the catalog-only search API."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.catalog_search import router as catalog_search_router, search_catalog
from app.db import make_engine
from app.models import Brand, Fragrance, Offer, ProductVariant, Store


def test_catalog_search_reads_seeded_identity_without_retailer_search():
    engine = make_engine()
    assert engine.dialect.name == "postgresql"
    api = FastAPI()
    api.include_router(catalog_search_router)
    try:
        with TestClient(api) as client:
            response = client.get("/catalog/search", params={"q": "Sauvage"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["query"] == "Sauvage"
        assert payload["count"] >= 1
        product = next(
            row for row in payload["results"]
            if row["brand"].lower() == "dior"
            and row["fragrance"].lower() == "sauvage"
        )
        assert any(
            variant["size_ml"] == 100
            and (variant["concentration"] or "").lower() in {"edp", "eau de parfum"}
            for variant in product["variants"]
        )
    finally:
        engine.dispose()


def test_catalog_search_rejects_too_short_query():
    engine = make_engine()
    try:
        from app.api.catalog_search import search_catalog
        from fastapi import HTTPException
        try:
            search_catalog(" ")
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("blank search query should be rejected")
    finally:
        engine.dispose()


def test_catalog_search_returns_only_published_offers_from_active_stores():
    engine = make_engine()
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as session:
            variant = session.scalar(
                select(ProductVariant)
                .join(Fragrance, Fragrance.id == ProductVariant.fragrance_id)
                .join(Brand, Brand.id == Fragrance.brand_id)
                .where(
                    Brand.name.ilike("Dior"),
                    Fragrance.name.ilike("Sauvage"),
                    ProductVariant.size_ml == 100,
                )
            )
            assert variant is not None

            active_store = Store(
                name="Fixture Active Store",
                slug="catalog-search-active-fixture",
                currency="EUR",
                status="active",
            )
            inactive_store = Store(
                name="Fixture Inactive Store",
                slug="catalog-search-inactive-fixture",
                currency="EUR",
                status="inactive",
            )
            session.add_all([active_store, inactive_store])
            session.flush()

            session.add_all([
                Offer(
                    store_id=active_store.id,
                    product_variant_id=variant.id,
                    url="https://fixture.example/active-offer",
                    price=Decimal("89.90"),
                    currency="EUR",
                    availability="in_stock",
                    source="catalog_search_test_fixture",
                    status="active",
                ),
                Offer(
                    store_id=inactive_store.id,
                    product_variant_id=variant.id,
                    url="https://fixture.example/inactive-store-offer",
                    price=Decimal("79.90"),
                    currency="EUR",
                    availability="in_stock",
                    source="catalog_search_test_fixture",
                    status="active",
                ),
            ])
            session.commit()

        payload = search_catalog("Sauvage", session_factory=factory)
        product = next(
            row for row in payload["results"]
            if row["brand"].lower() == "dior"
            and row["fragrance"].lower() == "sauvage"
        )
        variant_result = next(
            row for row in product["variants"]
            if row["size_ml"] == 100
        )
        assert len(variant_result["offers"]) == 1
        assert variant_result["offers"][0]["store"] == "catalog-search-active-fixture"
        assert variant_result["offers"][0]["price"] == 89.9
        assert variant_result["offers"][0]["ranking"]["position"] == 1
        assert 0 <= variant_result["offers"][0]["ranking"]["score"] <= 100
        assert "shipping_transparency" in variant_result["offers"][0]["ranking"]["components"]

        # A caller-owned session factory remains usable after the search.
        with factory() as session:
            assert session.scalar(select(Store).where(
                Store.slug == "catalog-search-active-fixture"
            )) is not None
    finally:
        engine.dispose()



def test_catalog_search_router_is_mounted_in_the_real_fastapi_application():
    # Import the deployed application module, not a temporary FastAPI instance.
    # Do not enter TestClient's lifespan context: that would start legacy
    # background catalog workers, which this route-registration test does not need.
    from main import app as scenthunter_app

    client = TestClient(scenthunter_app)
    response = client.get("/catalog/search", params={"q": "Sauvage"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["query"] == "Sauvage"
    assert any(
        row["brand"].lower() == "dior"
        and row["fragrance"].lower() == "sauvage"
        for row in payload["results"]
    )


def test_existing_frontend_search_route_can_opt_into_postgres_catalog(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_CATALOG_SEARCH_ENABLED", "1")
    from main import app as scenthunter_app

    client = TestClient(scenthunter_app)
    response = client.get("/search-start", params={"q": "Sauvage"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["completed"] is True
    assert payload["status"] == "completed"
    assert payload["query"] == "Sauvage"
    assert payload["count"] >= 1
    assert payload["offer_count"] >= 1

    product = next(
        row for row in payload["results"]
        if row["brand"].lower() == "dior"
        and row["fragrance"].lower() == "sauvage"
    )
    assert product["catalog_id"]
    assert any(
        offer["store"] == "catalog-search-active-fixture"
        and offer["phase2_offer_id"]
        and offer["size_ml"] == 100
        for offer in product["offers"]
    )


def test_catalog_search_ranks_quality_above_cheapest_offer():
    engine = make_engine()
    assert engine.dialect.name == "postgresql"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    store_ids = []
    offer_ids = []
    try:
        with factory.begin() as session:
            variant = session.scalar(
                select(ProductVariant)
                .join(Fragrance, Fragrance.id == ProductVariant.fragrance_id)
                .where(
                    Fragrance.name.ilike("%Sauvage%"),
                    ProductVariant.canonical_key.ilike("%|edp|100"),
                )
                .limit(1)
            )
            assert variant is not None
            weak_store = Store(
                name="CI Weak Retailer",
                slug="ci-weak-retailer",
                status="active",
                reliability_score=Decimal("0.100"),
            )
            strong_store = Store(
                name="CI Strong Retailer",
                slug="ci-strong-retailer",
                status="active",
                reliability_score=Decimal("1.000"),
            )
            session.add_all([weak_store, strong_store])
            session.flush()
            store_ids.extend([weak_store.id, strong_store.id])

            cheap_stale = Offer(
                store_id=weak_store.id,
                product_variant_id=variant.id,
                url="https://example.invalid/ci-cheap-stale",
                price=Decimal("40.00"),
                currency="EUR",
                availability="out_of_stock",
                source="ci_fixture",
                confidence=Decimal("0.300"),
                captured_at=now - timedelta(days=14),
                status="active",
            )
            reliable_fresh = Offer(
                store_id=strong_store.id,
                product_variant_id=variant.id,
                url="https://example.invalid/ci-reliable-fresh",
                price=Decimal("80.00"),
                currency="EUR",
                availability="in_stock",
                shipping_cost=Decimal("0.00"),
                source="ci_fixture",
                confidence=Decimal("1.000"),
                captured_at=now - timedelta(minutes=20),
                status="active",
            )
            session.add_all([cheap_stale, reliable_fresh])
            session.flush()
            offer_ids.extend([cheap_stale.id, reliable_fresh.id])

        payload = search_catalog("Sauvage", session_factory=factory)
        product = next(
            row for row in payload["results"]
            if any(v["variant_id"] == str(variant.id) for v in row["variants"])
        )
        ranked = next(
            v["offers"] for v in product["variants"]
            if v["variant_id"] == str(variant.id)
        )
        ranked_ids = [row["offer_id"] for row in ranked]
        assert ranked_ids.index(str(reliable_fresh.id)) < ranked_ids.index(str(cheap_stale.id))
        strong_row = next(row for row in ranked if row["offer_id"] == str(reliable_fresh.id))
        assert strong_row["ranking"]["score"] > next(
            row["ranking"]["score"] for row in ranked
            if row["offer_id"] == str(cheap_stale.id)
        )
    finally:
        with factory.begin() as session:
            if offer_ids:
                session.query(Offer).filter(Offer.id.in_(offer_ids)).delete(synchronize_session=False)
            if store_ids:
                session.query(Store).filter(Store.id.in_(store_ids)).delete(synchronize_session=False)
        engine.dispose()

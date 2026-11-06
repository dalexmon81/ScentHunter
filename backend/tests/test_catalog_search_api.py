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
                offer_ttl_minutes=1440,
                status="active",
            )
            inactive_store = Store(
                name="Fixture Inactive Store",
                slug="catalog-search-inactive-fixture",
                currency="EUR",
                status="inactive",
            )
            expired_store = Store(
                name="Fixture Expired Offer Store",
                slug="catalog-search-expired-fixture",
                currency="EUR",
                status="active",
            )
            session.add_all([active_store, inactive_store, expired_store])
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
                    valid_until=datetime.now(timezone.utc) + timedelta(hours=24),
                ),
                Offer(
                    store_id=active_store.id,
                    product_variant_id=variant.id,
                    url="https://fixture.example/missing-expiry-offer",
                    price=Decimal("88.90"),
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
                Offer(
                    store_id=expired_store.id,
                    product_variant_id=variant.id,
                    url="https://fixture.example/expired-offer",
                    price=Decimal("69.90"),
                    currency="EUR",
                    availability="in_stock",
                    source="catalog_search_test_fixture",
                    status="active",
                    valid_until=datetime.now(timezone.utc) - timedelta(minutes=1),
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
        fixture_offers = [offer for offer in variant_result["offers"] if offer["store"] == "catalog-search-active-fixture"]
        assert len(fixture_offers) == 1
        assert fixture_offers[0]["price"] == 89.9
        assert fixture_offers[0]["ranking"]["currency_scope"] == "EUR"
        assert fixture_offers[0]["ranking"]["score"] > 0
        assert fixture_offers[0]["ranking"]["shipping_cost_known"] is False
        assert fixture_offers[0]["ranking"]["price_basis"] == "product_price_only"
        assert all(offer["store"] != "catalog-search-inactive-fixture" for offer in variant_result["offers"])
        assert all(offer["store"] != "catalog-search-expired-fixture" for offer in variant_result["offers"])
        assert all(offer["url"] != "https://fixture.example/missing-expiry-offer" for offer in variant_result["offers"])

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
    monkeypatch.setenv("SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT", "100")
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


def test_catalog_search_full_text_matches_tokens_across_brand_and_fragrance():
    engine = make_engine()
    assert engine.dialect.name == "postgresql"
    try:
        combined = search_catalog("Dior Sauvage")
        assert combined["count"] >= 1
        assert any(
            row["brand"].lower() == "dior"
            and row["fragrance"].lower() == "sauvage"
            for row in combined["results"]
        )

        incomplete = search_catalog("Dior NotARealFragrance")
        assert incomplete["count"] == 0
        assert incomplete["results"] == []
    finally:
        engine.dispose()

from datetime import datetime, timedelta, timezone
import os
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.models import Base, Brand, Fragrance, Offer, ProductVariant, Store
from app.search.catalog_search import search_catalog


def _factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-search.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    brand_id, fragrance_id = uuid4(), uuid4()
    variant_id, tester_id = uuid4(), uuid4()
    store_id, second_store_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with factory() as session:
        session.add(Brand(
            id=brand_id, name="Dior", slug="dior", normalized_name="dior",
        ))
        session.add(Fragrance(
            id=fragrance_id, brand_id=brand_id, name="Sauvage",
            slug="sauvage", family="aromatic", gender="men",
        ))
        session.add_all([
            ProductVariant(
                id=variant_id, fragrance_id=fragrance_id, concentration="EDP",
                size_ml=100, is_tester=False, canonical_key="dior|sauvage|edp|100",
            ),
            ProductVariant(
                id=tester_id, fragrance_id=fragrance_id, concentration="EDP",
                size_ml=100, is_tester=True, canonical_key="dior|sauvage|edp|100|tester",
            ),
        ])
        session.add_all([
            Store(id=store_id, name="Notino", slug="notino", country="FR",
                  currency="EUR", status="active"),
            Store(id=second_store_id, name="Inactive Shop", slug="inactive-shop",
                  country="FR", currency="EUR", status="quarantined"),
        ])
        session.add_all([
            Offer(
                id=uuid4(), store_id=store_id, product_variant_id=variant_id,
                external_product_id="sauvage-100", url="https://notino.example/sauvage",
                price=Decimal("89.90"), currency="EUR", availability="in_stock",
                source="fixture", confidence=Decimal("1.000"), captured_at=now,
                status="active", publication_status="published",
            ),
            Offer(
                id=uuid4(), store_id=store_id, product_variant_id=tester_id,
                external_product_id="sauvage-tester", url="https://notino.example/sauvage-tester",
                price=Decimal("69.90"), currency="EUR", availability="in_stock",
                source="fixture", confidence=Decimal("1.000"), captured_at=now,
                status="active", publication_status="draft",
            ),
            Offer(
                id=uuid4(), store_id=store_id, product_variant_id=variant_id,
                external_product_id="sauvage-stale", url="https://notino.example/sauvage-old",
                price=Decimal("49.90"), currency="EUR", availability="in_stock",
                source="fixture", confidence=Decimal("1.000"),
                captured_at=now - timedelta(hours=72),
                status="active", publication_status="published",
            ),
            Offer(
                id=uuid4(), store_id=second_store_id, product_variant_id=variant_id,
                external_product_id="sauvage-inactive", url="https://inactive.example/sauvage",
                price=Decimal("39.90"), currency="EUR", availability="in_stock",
                source="fixture", confidence=Decimal("1.000"), captured_at=now,
                status="active", publication_status="published",
            ),
        ])
        session.commit()
    return factory, engine


def test_catalog_search_returns_only_fresh_published_offers(tmp_path):
    factory, engine = _factory(tmp_path)
    try:
        result = search_catalog("Sauvage", session_factory=factory)
        assert result["count"] == 1
        assert result["offer_count"] == 1
        product = result["results"][0]
        assert product["brand"] == "Dior"
        assert product["fragrance"] == "Sauvage"
        assert product["variant_selection_required"] is True
        assert len(product["variants"]) == 2
        offered_variant = next(item for item in product["variants"] if item["offers"])
        assert offered_variant["size_ml"] == 100
        assert offered_variant["offers"][0]["store"] == "notino"
        assert offered_variant["offers"][0]["price"] == "89.90"
        assert offered_variant["min_price"] == "89.90"
        assert offered_variant["store_count"] == 1
        assert offered_variant["availability"] == "in_stock"
    finally:
        engine.dispose()


def test_catalog_search_filters_store_country_currency_and_price(tmp_path):
    factory, engine = _factory(tmp_path)
    try:
        result = search_catalog(
            "Sauvage", session_factory=factory, store="notino",
            country="FR", currency="EUR", min_price=Decimal("80"),
            max_price=Decimal("100"),
        )
        assert result["offer_count"] == 1
        assert result["results"][0]["variants"][0]["offers"][0]["price"] == "89.90"
    finally:
        engine.dispose()


def test_catalog_search_can_filter_variant_format(tmp_path):
    factory, engine = _factory(tmp_path)
    try:
        result = search_catalog(
            "Sauvage", session_factory=factory, product_format="tester",
        )
        assert result["count"] == 1
        assert result["offer_count"] == 0
        assert result["results"][0]["variants"][0]["offers"] == []
        assert "non ci sono offerte" in result["message"]
    finally:
        engine.dispose()


def test_catalog_search_rejects_unsupported_format_and_long_query(tmp_path):
    factory, engine = _factory(tmp_path)
    try:
        import pytest
        with pytest.raises(ValueError, match="unsupported_product_format"):
            search_catalog("Sauvage", session_factory=factory, product_format="giftbox")
        with pytest.raises(ValueError, match="query_too_long"):
            search_catalog("x" * 161, session_factory=factory)
    finally:
        engine.dispose()


def test_postgres_full_text_catalog_search_reads_published_variant():
    import pytest

    url = os.environ.get("SCENTHUNTER_CATALOG_DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("requires disposable PostgreSQL full-text search database")

    engine = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    brand_id, fragrance_id, variant_id = uuid4(), uuid4(), uuid4()
    store_id, offer_id = uuid4(), uuid4()
    slug = "fts-test-" + store_id.hex
    now = datetime.now(timezone.utc)
    try:
        with factory.begin() as session:
            session.add(Brand(
                id=brand_id, name="Dior", slug=slug,
                normalized_name=slug,
            ))
            session.add(Fragrance(
                id=fragrance_id, brand_id=brand_id,
                name="Sauvage FTS Probe", slug=slug,
                olfactory_notes=["bergamot", "pepper"],
            ))
            session.add(ProductVariant(
                id=variant_id, fragrance_id=fragrance_id,
                concentration="EDP", size_ml=100,
                canonical_key=slug,
            ))
            session.add(Store(
                id=store_id, name="FTS Test Store", slug=slug,
                country="LU", currency="EUR", status="active",
            ))
            session.add(Offer(
                id=offer_id, store_id=store_id,
                product_variant_id=variant_id,
                external_product_id=slug,
                url="https://fts.example.invalid/item",
                price=Decimal("42.00"), currency="EUR",
                availability="in_stock", source="test",
                confidence=Decimal("1.000"), captured_at=now,
                status="active", publication_status="published",
            ))

        result = search_catalog(
            "Dior Bergamot", session_factory=factory, store=slug,
        )
        assert result["count"] == 1
        assert result["offer_count"] == 1
        assert result["results"][0]["fragrance"] == "Sauvage FTS Probe"
    finally:
        with factory.begin() as session:
            session.execute(delete(Offer).where(Offer.id == offer_id))
            session.execute(delete(ProductVariant).where(ProductVariant.id == variant_id))
            session.execute(delete(Fragrance).where(Fragrance.id == fragrance_id))
            session.execute(delete(Store).where(Store.id == store_id))
            session.execute(delete(Brand).where(Brand.id == brand_id))
        engine.dispose()


def test_catalog_search_returns_similar_suggestions_when_not_found(tmp_path):
    factory, engine = _factory(tmp_path)
    try:
        result = search_catalog("Dior SauvagX", session_factory=factory)
        assert result["count"] == 0
        assert result["suggestions"]
        assert result["suggestions"][0]["fragrance"] == "Sauvage"
    finally:
        engine.dispose()

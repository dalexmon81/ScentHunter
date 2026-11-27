from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Offer, Store
from app.workers import postgres_worker


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_daily_discovery_scheduler_queues_only_stores_with_configured_queries(monkeypatch):
    engine, sessions = _session_factory()
    try:
        with sessions() as session, session.begin():
            notino = Store(
                name="Notino.fr", slug="notino-fr", domain="www.notino.fr",
                country="FR", currency="EUR", status="active",
            )
            deloox = Store(
                name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
                country="BE", currency="EUR", status="active",
            )
            diagnostic = Store(
                name="PerfumeMarket", slug="perfumemarket",
                domain="perfumemarket.com", country="NL",
                currency="EUR", status="active",
            )
            session.add_all([notino, deloox, diagnostic])
            session.flush()
            notino_id, deloox_id = notino.id, deloox.id

        monkeypatch.setenv("SCENTHUNTER_DISCOVERY_QUERIES_DELOOX", "Dior Sauvage;Afnan 9PM")
        monkeypatch.delenv("SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET", raising=False)
        calls = []
        monkeypatch.setattr(
            postgres_worker, "enqueue_daily_once",
            lambda key, stage, payload, day: calls.append((key, stage, payload, day)) or "job-id",
        )

        postgres_worker._schedule_daily_discovery(sessions)

        assert {call[0] for call in calls} == {
            "schedule:notino-fr:daily-discovery",
            "schedule:deloox-be:daily-discovery",
        }
        for _key, stage, payload, day in calls:
            assert stage == "discover"
            assert payload["cursor"] is None
            assert payload["limit"] == 100
            assert payload["store_id"] in {str(notino_id), str(deloox_id)}
            assert day


def test_active_offer_refresh_scheduler_uses_retailer_fetch_identity(monkeypatch):
    engine, sessions = _session_factory()
    try:
        with sessions() as session, session.begin():
            deloox = Store(
                name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
                country="BE", currency="EUR", status="active",
            )
            bplatz = Store(
                name="Bplatz", slug="bplatz", domain="bplatz.de",
                country="DE", currency="EUR", status="active",
            )
            notino = Store(
                name="Notino.fr", slug="notino-fr", domain="www.notino.fr",
                country="FR", currency="EUR", status="active",
            )
            session.add_all([deloox, bplatz, notino])
            session.flush()
            expected = {
                deloox.id: "DELOOX-SKU-1",
                bplatz.id: "https://bplatz.de/products/liquid-brun",
                notino.id: "https://www.notino.fr/dior/sauvage/",
            }
            for store, external_id, url in (
                (deloox, "DELOOX-SKU-1", "https://www.deloox.be/produit/1"),
                (bplatz, "6290360375694", "https://bplatz.de/products/liquid-brun"),
                (notino, "https://www.notino.fr/dior/sauvage/", "https://www.notino.fr/dior/sauvage/"),
            ):
                session.add(Offer(
                    store_id=store.id, external_product_id=external_id,
                    url=url, price=Decimal("50.00"), currency="EUR",
                    availability="in_stock", source="fixture", status="active",
                ))

        monkeypatch.setenv("SCENTHUNTER_ACTIVE_OFFER_REFRESH_ENABLED", "1")
        calls = []
        monkeypatch.setattr(
            postgres_worker, "enqueue_offer_refresh",
            lambda store_id, external_id: calls.append((store_id, external_id)),
        )

        postgres_worker._schedule_active_offer_refresh(sessions)

        assert set(calls) == set(expected.items())
    finally:
        engine.dispose()

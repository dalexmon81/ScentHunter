"""End-to-end Bplatz persistence contract against disposable PostgreSQL."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import (  # noqa: E402
    Base, Brand, Fragrance, ProductVariant, Store, LegacyProductIdMap,
    LegacyVariantIdMap, IngestionRaw, Offer, PriceHistory, MatchAudit,
)
from app.services.bplatz_phase2_adapter import persist_bplatz_record  # noqa: E402
from app.services.ingestion_persistence import PromotionRejected  # noqa: E402


DATABASE_URL = os.environ.get("SCENTHUNTER_TEST_POSTGRES_URL", "")


@unittest.skipUnless(DATABASE_URL, "requires disposable PostgreSQL service")
def test_real_bplatz_stage_match_promote_and_repeat_hydration_on_postgres():
    from scrapers.bplatz.scraper import parse_product_html
    from scenthunter_next_engine.next_engine_service import NextEngineService
    from scenthunter_next_engine.offer_normalizer import normalize_offer

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        # CI owns this disposable database. Clear only this dedicated test DB,
        # respecting FK order; never point this test at a production DSN.
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))

        seed_env = os.environ.copy()
        seed_env["SCENTHUNTER_CATALOG_DATABASE_URL"] = DATABASE_URL
        seed_env["PYTHONPATH"] = str(BACKEND) + os.pathsep + seed_env.get("PYTHONPATH", "")
        seeded = subprocess.run(
            [sys.executable, str(BACKEND / "scripts/seed_catalog.py"),
             "--catalog", str(BACKEND / "product_catalog.json"), "--apply", "--seed-bplatz-store"],
            cwd=ROOT, env=seed_env, text=True, capture_output=True, check=False,
        )
        assert seeded.returncode == 0, (
            "Canonical seed failed\n" + seeded.stdout + "\n" + seeded.stderr
        )
        seed_report = json.loads(seeded.stdout)
        assert seed_report["status"] == "seeded"
        assert seed_report["database_written"] is True
        assert seed_report["database_counts"]["legacy_product_id_map"] > 0
        assert seed_report["database_counts"]["legacy_variant_id_map"] > 0

        fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
        meta = json.loads(
            (ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json").read_text()
        )
        parsed = parse_product_html(
            fixture.read_text(encoding="utf-8"), meta["url_final"],
            "French Avenue Liquid Brun",
        )
        assert parsed is not None
        record = {
            "raw_name": parsed["name"], "brand_raw": parsed["brand"],
            "size_ml": parsed["size_ml"], "price": parsed["price_num"],
            "currency": parsed["offer"]["currency"],
            "product_url": parsed["url"], "availability": parsed["availability"],
            "sku": parsed["sku"], "gtin": parsed["gtin"],
        }
        normalized = normalize_offer(record, retailer="Bplatz", currency_default="EUR")
        matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
        matched = matcher.process_offers([normalized])
        assert matched.matched_offer_count == 1
        group = matched.groups[0]
        assert group.canonical_product_id == "SH-0030"
        assert group.canonical_variant_id == "VAR-f87146c82d167f4c"

        with Session(engine) as session, session.begin():
            store = session.scalar(select(Store).where(Store.slug == "bplatz"))
            assert store is not None
            store_id = store.id
            first = persist_bplatz_record(
                session, store_id=store_id, raw_record=dict(record), matcher=matcher,
            )
            assert first.status == "promoted"
            assert first.offer_id is not None
            assert first.product_variant_id is not None
            assert first.fragrance_id is not None

        with Session(engine) as session:
            offer = session.get(Offer, first.offer_id)
            raw = session.get(IngestionRaw, first.ingestion_raw_id)
            assert offer is not None and offer.product_variant_id == first.product_variant_id
            assert offer.price == normalized.price
            assert offer.currency == "EUR"
            assert offer.url == normalized.product_url
            assert offer.availability in {"in_stock", "out_of_stock"}
            assert raw is not None and raw.status == "promoted"
            assert raw.legacy_product_id == group.canonical_product_id
            assert raw.legacy_variant_id == group.canonical_variant_id
            assert session.scalar(select(func.count()).select_from(PriceHistory).where(
                PriceHistory.offer_id == first.offer_id
            )) == 1
            assert session.scalar(select(func.count()).select_from(MatchAudit).where(
                MatchAudit.offer_id == first.offer_id
            )) == 1

        # A later hydration updates the same retailer offer and appends an
        # auditable price observation; it must not create a duplicate Offer.
        updated = dict(record)
        updated["price"] = float(normalized.price + Decimal("1.00"))
        with Session(engine) as session, session.begin():
            second = persist_bplatz_record(
                session, store_id=store_id, raw_record=updated, matcher=matcher,
            )
            assert second.status == "promoted"
            assert second.offer_id == first.offer_id

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Offer)) == 1
            assert session.scalar(select(func.count()).select_from(PriceHistory)) == 2
            assert session.scalar(select(func.count()).select_from(MatchAudit)) == 2
            offer = session.get(Offer, first.offer_id)
            assert offer.price == Decimal(str(updated["price"]))
            assert offer.ingestion_raw_id == second.ingestion_raw_id

        # An unknown product remains staged; it cannot become a published offer.
        unknown = {
            "raw_name": "Unknown Test Fragrance 998877",
            "brand_raw": "Unknown Test Brand",
            "size_ml": 100, "price": 29.90, "currency": "EUR",
            "product_url": "https://en.bplatz.de/products/unknown-test",
            "availability": "in_stock", "sku": "BPLATZ-UNKNOWN-998877",
        }
        with Session(engine) as session, session.begin():
            unmatched = persist_bplatz_record(
                session, store_id=store_id, raw_record=unknown, matcher=matcher,
            )
            assert unmatched.status == "pending"
            assert unmatched.offer_id is None
        with Session(engine) as session:
            raw = session.get(IngestionRaw, unmatched.ingestion_raw_id)
            assert raw is not None and raw.status == "pending"
            assert raw.product_variant_id is None
            assert session.scalar(select(func.count()).select_from(Offer)) == 1

        # Caller-owned transaction rollback must undo staging and promotion.
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "forced rollback"):
            with Session(engine) as session, session.begin():
                rollback_result = persist_bplatz_record(
                    session, store_id=store_id, raw_record=dict(record), matcher=matcher,
                )
                assert rollback_result.status == "promoted"
                raise RuntimeError("forced rollback")
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Offer)) == 1
            assert session.scalar(select(func.count()).select_from(IngestionRaw)) == 3

    finally:
        engine.dispose()


def test_hydration_worker_persists_bplatz_offer_on_postgres(monkeypatch):
    """Exercise the durable hydration worker context against disposable PostgreSQL."""
    from unittest.mock import patch
    import catalog_engine
    from scrapers.bplatz.scraper import parse_product_html

    assert DATABASE_URL, "requires disposable PostgreSQL service"
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))

        seed_env = os.environ.copy()
        seed_env["SCENTHUNTER_CATALOG_DATABASE_URL"] = DATABASE_URL
        seed_env["PYTHONPATH"] = str(BACKEND) + os.pathsep + seed_env.get("PYTHONPATH", "")
        seeded = subprocess.run(
            [sys.executable, str(BACKEND / "scripts/seed_catalog.py"),
             "--catalog", str(BACKEND / "product_catalog.json"), "--apply", "--seed-bplatz-store"],
            cwd=ROOT, env=seed_env, text=True, capture_output=True, check=False,
        )
        assert seeded.returncode == 0, seeded.stdout + "\\n" + seeded.stderr

        fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
        meta = json.loads(
            (ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json").read_text()
        )
        parsed = parse_product_html(
            fixture.read_text(encoding="utf-8"), meta["url_final"],
            "French Avenue Liquid Brun",
        )
        assert parsed is not None
        item = {
            "name": parsed["name"], "brand": parsed["brand"],
            "size_ml": parsed["size_ml"], "price_num": parsed["price_num"],
            "currency": parsed["offer"]["currency"], "url": parsed["url"],
            "availability": parsed["availability"], "sku": parsed["sku"],
            "gtin": parsed.get("gtin"), "mpn": parsed.get("mpn"),
            "concentration": parsed.get("concentration"),
        }
        completed = []
        task = {"store": "bplatz", "url": item["url"], "attempts": 1}
        with patch.dict(os.environ, {
            "SCENTHUNTER_CATALOG_DATABASE_URL": DATABASE_URL,
            "BPLATZ_PHASE2_PERSISTENCE": "1",
        }):
            with patch.object(catalog_engine, "_foreground_search_running", return_value=False):
                with patch.object(catalog_engine, "_queue_mark_done", side_effect=lambda row: completed.append(row)):
                    with patch.object(catalog_engine, "refresh_url", side_effect=lambda store, url: (
                        item if catalog_engine._maybe_persist_bplatz_phase2(item, url) else item
                    )):
                        assert catalog_engine._hydrate_one_task(task) is True

        assert completed == [task]
        with Session(engine) as session:
            offer = session.scalar(select(Offer))
            assert offer is not None
            assert offer.price > 0
            assert offer.currency == "EUR"
            assert offer.url == item["url"]
            assert session.scalar(select(func.count()).select_from(IngestionRaw)) == 1
            assert session.scalar(select(func.count()).select_from(PriceHistory)) == 1
            assert session.scalar(select(func.count()).select_from(MatchAudit)) == 1
    finally:
        engine.dispose()

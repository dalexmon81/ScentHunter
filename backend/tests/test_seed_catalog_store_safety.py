"""Safety contract for canonical catalog seeding and retailer activation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SEED = BACKEND / "scripts" / "seed_catalog.py"
CATALOG = BACKEND / "product_catalog.json"


def run_seed(*extra: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SEED), "--catalog", str(CATALOG), *extra],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    return json.loads(completed.stdout)


def test_default_dry_run_does_not_activate_any_retailer():
    report = run_seed()
    assert report["status"] == "validated"
    assert report["stores_to_seed"] == []
    assert report["offers_imported"] == 0
    assert report["database_written"] is False
    assert report["source_modified"] is False


def test_bplatz_activation_requires_explicit_opt_in():
    report = run_seed("--seed-bplatz-store")
    assert report["status"] == "validated"
    assert [store["slug"] for store in report["stores_to_seed"]] == ["bplatz"]
    assert report["database_written"] is False
    assert report["source_modified"] is False



def test_notino_activation_requires_explicit_opt_in():
    report = run_seed("--seed-notino-store")
    assert report["status"] == "validated"
    assert [store["slug"] for store in report["stores_to_seed"]] == ["notino-fr"]
    assert report["database_written"] is False
    assert report["source_modified"] is False


class LegacyRetailerSeedOptInTests(unittest.TestCase):
    def test_legacy_retailer_activation_requires_explicit_opt_in(self):
        report = run_seed(
            "--seed-deloox-store", "--seed-sabina-store",
            "--seed-easycosmetic-store", "--seed-parfumzentrum-store",
        )
        self.assertEqual(report["status"], "validated")
        self.assertEqual(
            [store["slug"] for store in report["stores_to_seed"]],
            ["deloox-be", "sabina-es", "easycosmetic-de", "parfumzentrum-de"],
        )
        self.assertFalse(report["database_written"])
        self.assertFalse(report["source_modified"])


def test_seed_reuses_existing_brand_when_slug_matches_but_normalized_name_differs():
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import Brand
    from scripts.seed_catalog import get_or_create_brand

    engine = create_engine("sqlite:///:memory:")
    Brand.__table__.create(engine)
    try:
        with Session(engine) as session, session.begin():
            existing = Brand(
                name="Viktor & Rolf",
                slug="viktor-rolf",
                normalized_name="viktor rolf",
            )
            session.add(existing)
            session.flush()

            resolved = get_or_create_brand(session, "viktor and rolf", "Viktor & Rolf")
            assert resolved.id == existing.id
            assert session.scalar(select(Brand).where(Brand.slug == "viktor-rolf")).id == existing.id
            assert len(session.scalars(select(Brand)).all()) == 1
    finally:
        engine.dispose()


def test_seed_stops_when_normalized_name_and_slug_point_to_different_brands():
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models import Brand
    from scripts.seed_catalog import get_or_create_brand

    engine = create_engine("sqlite:///:memory:")
    Brand.__table__.create(engine)
    try:
        with Session(engine) as session, session.begin():
            session.add_all([
                Brand(name="Viktor Rolf", slug="viktor-rolf", normalized_name="viktor rolf"),
                Brand(name="Viktor & Rolf", slug="viktor-and-rolf", normalized_name="viktor and rolf"),
            ])
            session.flush()
            with pytest.raises(RuntimeError, match="Brand identity conflict"):
                get_or_create_brand(session, "viktor and rolf", "Viktor & Rolf")
    finally:
        engine.dispose()





class ExistingRetailerStateSafetyTests(unittest.TestCase):
    def _run_with_store(self, store, retailer_flag="--seed-deloox-store"):
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from app.models import Base, Store

        store_slug = store.slug
        with tempfile.TemporaryDirectory() as temp:
            database_url = "sqlite:///" + str(Path(temp) / "catalog.sqlite3")
            engine = create_engine(database_url)
            try:
                Base.metadata.create_all(engine)
                store_slug = store.slug
                with Session(engine) as session, session.begin():
                    session.add(store)
                env = os.environ.copy()
                env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
                completed = subprocess.run(
                    [sys.executable, str(SEED), "--catalog", str(CATALOG),
                     "--apply", retailer_flag],
                    cwd=ROOT, env=env, text=True, capture_output=True, check=False,
                )
                with Session(engine) as session:
                    persisted = session.scalar(select(Store).where(Store.slug == store_slug))
                    snapshot = {
                        "status": persisted.status,
                        "domain": persisted.domain,
                        "name": persisted.name,
                        "reliability_score": persisted.reliability_score,
                        "last_successful_sync_at": persisted.last_successful_sync_at,
                    }
                return completed, snapshot
            finally:
                engine.dispose()

    def test_existing_inactive_store_is_not_reactivated(self):
        from app.models import Store

        completed, persisted = self._run_with_store(Store(
            name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
            country="BE", currency="EUR", status="inactive",
        ))
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("refusing automatic reactivation", completed.stderr)
        self.assertEqual(persisted["status"], "inactive")

    def test_existing_active_store_metadata_and_health_state_are_preserved(self):
        from datetime import datetime
        from app.models import Store

        synced_at = datetime(2026, 11, 21, 12, 0)
        completed, persisted = self._run_with_store(Store(
            name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
            country="BE", currency="EUR", status="active",
            reliability_score=0.93, last_successful_sync_at=synced_at,
        ))
        self.assertEqual(completed.returncode, 0, completed.stdout + "\\n" + completed.stderr)
        self.assertEqual(persisted["status"], "active")
        self.assertEqual(persisted["domain"], "www.deloox.be")
        self.assertEqual(float(persisted["reliability_score"]), 0.93)
        self.assertEqual(persisted["last_successful_sync_at"], synced_at)


class CanonicalGtinImportTests(unittest.TestCase):
    def test_extract_variant_gtin_reads_plural_catalog_field_and_checks_digit(self):
        from scripts.seed_catalog import extract_variant_gtin

        self.assertEqual(extract_variant_gtin({"gtins": ["3348901368247"]}), "3348901368247")
        self.assertEqual(
            extract_variant_gtin({"gtin": "3348901368247", "gtins": ["3348901368247"]}),
            "3348901368247",
        )

    def test_extract_variant_gtin_rejects_invalid_and_ambiguous_codes(self):
        from scripts.seed_catalog import extract_variant_gtin

        with self.assertRaisesRegex(ValueError, "check digit"):
            extract_variant_gtin({"gtins": ["3348901368248"]})
        with self.assertRaisesRegex(ValueError, "multiple GTINs"):
            extract_variant_gtin({"gtins": ["3348901368247", "3348901368254"]})

    def test_catalog_contains_verified_dior_sauvage_edp_100ml_variant(self):
        from scripts.seed_catalog import validate_catalog

        raw = json.loads(CATALOG.read_text(encoding="utf-8"))
        products, by_product, blocked = validate_catalog(raw)
        self.assertEqual(blocked, [])
        product = next(row for row in products if row["product_id"] == "SH-AUTO-0178")
        variants = by_product[product["product_id"]]
        target = [row for row in variants if row.get("size_ml") == 100]
        self.assertEqual(len(target), 1)
        self.assertEqual(target[0]["gtins"], ["3348901368247"])
        self.assertIs(target[0]["is_tester"], False)
        self.assertIs(target[0]["is_refill"], False)
        self.assertIs(target[0]["is_gift_set"], False)
        self.assertIs(target[0]["is_mini"], False)

    def test_seeded_dior_sauvage_edp_100ml_matches_notino_gtin_in_disposable_sqlite(self):
        from sqlalchemy import create_engine, select, func
        from sqlalchemy.orm import Session
        from app.models import Base, Store, ProductVariant, Offer
        from app.matching.canonical_matching import resolve_canonical_variant

        with tempfile.TemporaryDirectory() as temp:
            database_url = "sqlite:///" + str(Path(temp) / "catalog.sqlite3")
            engine = create_engine(database_url)
            try:
                Base.metadata.create_all(engine)
                env = os.environ.copy()
                env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
                completed = subprocess.run(
                    [
                        sys.executable, str(SEED), "--catalog", str(CATALOG),
                        "--apply", "--seed-notino-store",
                    ],
                    cwd=ROOT, env=env, text=True, capture_output=True, check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + "\\n" + completed.stderr)
                report = json.loads(completed.stdout)
                self.assertEqual(report["status"], "seeded")
                self.assertTrue(report["database_written"])

                # Re-importing the same canonical source must not duplicate
                # the Dior variant, GTIN owner or Notino store.
                repeated = subprocess.run(
                    [
                        sys.executable, str(SEED), "--catalog", str(CATALOG),
                        "--apply", "--seed-notino-store",
                    ],
                    cwd=ROOT, env=env, text=True, capture_output=True, check=False,
                )
                self.assertEqual(repeated.returncode, 0, repeated.stdout + "\\n" + repeated.stderr)
                self.assertEqual(json.loads(repeated.stdout)["status"], "seeded")

                with Session(engine) as session:
                    store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
                    self.assertIsNotNone(store)
                    result = resolve_canonical_variant(
                        session,
                        store_id=store.id,
                        external_product_id="CJ-DIOR-SAU-EDP-100",
                        record={
                            "gtin": "3348901368247",
                            "title": "Dior Sauvage Eau de Parfum 100 ml",
                            "brand": "Dior",
                            "concentration": "Eau de Parfum",
                            "size_ml": 100,
                        },
                    )
                    self.assertIsNotNone(result.match)
                    self.assertEqual(result.match.method, "gtin_exact")
                    variant = session.scalar(select(ProductVariant).where(
                        ProductVariant.gtin == "3348901368247"
                    ))
                    self.assertIsNotNone(variant)
                    self.assertEqual(result.match.product_variant_id, variant.id)
                    self.assertEqual(variant.size_ml, 100)
                    self.assertIs(variant.is_tester, False)
                    self.assertIs(variant.is_refill, False)
                    self.assertIs(variant.is_gift_set, False)
                    self.assertIs(variant.is_mini, False)
                    self.assertEqual(session.scalar(select(func.count()).select_from(Offer)), 0)

                    # Canonical identity and GTIN matching remain available
                    # internally, but public shopping search hides this variant
                    # until a retailer observation has been validated.
                    from app.search.catalog import search_catalog
                    before = search_catalog(session, "Dior Sauvage EDP 100 ml")
                    self.assertEqual(before["count"], 0)
                    self.assertEqual(before["offer_count"], 0)

                    from app.connectors.notino_feed import NotinoAffiliateFeedConnector
                    from app.offers.ingestion import persist_connector_record
                    from scenthunter_next_engine.next_engine_service import NextEngineService

                    connector = NotinoAffiliateFeedConnector(
                        feed_loader=lambda: b"", cache_ttl_seconds=0,
                    )
                    raw_record = {
                        "external_product_id": "CJ-DIOR-SAU-EDP-100",
                        "title": "Dior Sauvage Eau de Parfum 100 ml",
                        "brand": "Dior",
                        "gtin": "3348901368247",
                        "size_ml": 100,
                        "concentration": "Eau de Parfum",
                        "price": "89.90",
                        "currency": "EUR",
                        "currency_explicit": True,
                        "availability": "in_stock",
                        "product_url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/",
                        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/",
                        "affiliate_url": None,
                        "source": "authorized_cj_viv_xml_feed",
                        "raw_xml": "<product/>",
                        "source_updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    matcher = NextEngineService.from_catalog_file(CATALOG)
                    store_id = store.id
                    session.commit()
                    with session.begin():
                        ingested = persist_connector_record(
                            session,
                            connector=connector,
                            store_id=store_id,
                            raw_record=raw_record,
                            matcher=matcher,
                        )
                    self.assertEqual(ingested.status, "promoted")
                    self.assertIsNotNone(ingested.offer_id)
                    self.assertEqual(ingested.product_variant_id, variant.id)

                    # Legacy CJ/VIV ingestion can remain in historical storage,
                    # but it must never be surfaced as a current public Notino offer.
                    after = search_catalog(session, "Dior Sauvage EDP 100 ml")
                    self.assertEqual(after["count"], 0)
                    self.assertEqual(after["offer_count"], 0)
                    self.assertEqual(after["results"], [])
                    self.assertEqual(
                        session.scalar(select(func.count()).select_from(Offer)), 1,
                    )
            finally:
                engine.dispose()

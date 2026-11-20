"""Safety contract for canonical catalog seeding and retailer activation."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
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

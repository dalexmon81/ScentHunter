"""Safety contract for canonical catalog seeding and retailer activation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
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



def test_extract_variant_gtin_reads_plural_catalog_field_and_checks_digit():
    from scripts.seed_catalog import extract_variant_gtin

    assert extract_variant_gtin({"gtins": ["3348901368247"]}) == "3348901368247"
    assert extract_variant_gtin({"gtin": "3348901368247", "gtins": ["3348901368247"]}) == "3348901368247"


def test_extract_variant_gtin_rejects_invalid_and_ambiguous_codes():
    import pytest
    from scripts.seed_catalog import extract_variant_gtin

    with pytest.raises(ValueError, match="check digit"):
        extract_variant_gtin({"gtins": ["3348901368248"]})
    with pytest.raises(ValueError, match="multiple GTINs"):
        extract_variant_gtin({"gtins": ["3348901368247", "3348901368254"]})


def test_catalog_contains_verified_dior_sauvage_edp_100ml_variant():
    from scripts.seed_catalog import validate_catalog

    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    products, by_product, blocked = validate_catalog(raw)
    assert blocked == []
    product = next(row for row in products if row["product_id"] == "SH-AUTO-0178")
    variants = by_product[product["product_id"]]
    target = [row for row in variants if row.get("size_ml") == 100]
    assert len(target) == 1
    assert target[0]["gtins"] == ["3348901368247"]
    assert target[0]["is_tester"] is False
    assert target[0]["is_refill"] is False
    assert target[0]["is_gift_set"] is False
    assert target[0]["is_mini"] is False



def test_seeded_dior_sauvage_edp_100ml_matches_notino_gtin_in_disposable_sqlite():
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from app.models import Base, Store, ProductVariant, Offer
    from app.services.canonical_matching import resolve_canonical_variant

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
            assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
            report = json.loads(completed.stdout)
            assert report["status"] == "seeded"
            assert report["database_written"] is True

            with Session(engine) as session:
                store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
                assert store is not None
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
                assert result.match is not None
                assert result.match.method == "gtin_exact"
                variant = session.scalar(select(ProductVariant).where(
                    ProductVariant.gtin == "3348901368247"
                ))
                assert variant is not None
                assert result.match.product_variant_id == variant.id
                assert variant.size_ml == 100
                assert variant.is_tester is False
                assert variant.is_refill is False
                assert variant.is_gift_set is False
                assert variant.is_mini is False
                assert session.scalar(select(func.count()).select_from(Offer)) == 0
        finally:
            engine.dispose()

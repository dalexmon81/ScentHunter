from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, select


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SEED = BACKEND / "scripts" / "seed_catalog.py"


def sample_catalog() -> dict:
    return {
        "brands": [{"brand_id": "B1", "brand_name": "Test Brand"}],
        "products": [
            {
                "product_id": "P1",
                "brand_name": "Test Brand",
                "canonical_name": "Known Variant",
                "concentration": "EDP",
            },
            {
                "product_id": "P2",
                "brand_name": "Test Brand",
                "canonical_name": "Identity Only",
            },
        ],
        "variants": [
            {
                "variant_id": "V1",
                "product_id": "P1",
                "size_ml": 50,
            }
        ],
        "offers": [],
    }


def run_seed(catalog_path: Path, database_url: str, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, str(SEED), "--catalog", str(catalog_path), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_seed_dry_run_keeps_products_without_inventing_variants(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(sample_catalog()), encoding="utf-8")
    result = run_seed(catalog_path, f"sqlite:///{tmp_path / 'unused.sqlite3'}")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "validated"
    assert report["stores_to_seed"] == []
    assert report["brands"] == 1
    assert report["fragrances"] == 2
    assert report["variants"] == 1
    assert report["products_without_variants"] == 1
    assert report["offers_imported"] == 0
    assert report["database_written"] is False
    assert not (tmp_path / "unused.sqlite3").exists()


def test_bplatz_store_dry_run_requires_explicit_opt_in(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(sample_catalog()), encoding="utf-8")
    result = run_seed(
        catalog_path, f"sqlite:///{tmp_path / 'unused.sqlite3'}",
        "--seed-bplatz-store",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["stores_to_seed"] == [{
        "name": "Bplatz", "slug": "bplatz", "domain": "bplatz.de",
        "country": "DE", "currency": "EUR", "status": "active",
    }]
    assert report["database_written"] is False


def test_seed_apply_imports_identity_without_creating_variant_or_offer(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    database_path = tmp_path / "catalog.sqlite3"
    catalog_path.write_text(json.dumps(sample_catalog()), encoding="utf-8")
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migration.returncode == 0, migration.stderr

    result = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "seeded"
    assert report["database_written"] is True
    assert report["database_counts"]["brands"] == 1
    assert report["database_counts"]["fragrances"] == 2
    assert report["database_counts"]["product_variants"] == 1
    assert report["database_counts"]["legacy_product_id_map"] == 2
    assert report["database_counts"]["legacy_variant_id_map"] == 1
    assert report["database_counts"]["offers"] == 0

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT fragrance_id FROM legacy_product_id_map WHERE legacy_product_id='P1'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT product_variant_id FROM legacy_variant_id_map WHERE legacy_variant_id='V1'"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_product_id_map"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM fragrances f "
            "LEFT JOIN product_variants v ON v.fragrance_id = f.id "
            "WHERE v.id IS NULL"
        ).fetchone()[0] == 1


def test_seed_blocks_orphan_variant_without_writing_database(tmp_path):
    catalog = sample_catalog()
    catalog["variants"].append({
        "variant_id": "ORPHAN",
        "product_id": "MISSING",
        "size_ml": 100,
    })
    catalog_path = tmp_path / "catalog.json"
    database_path = tmp_path / "catalog.sqlite3"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    result = run_seed(catalog_path, f"sqlite:///{database_path}")

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["status"] == "blocked"
    assert report["database_written"] is False
    assert not database_path.exists()


def test_real_source_catalog_dry_run_reports_unmatched_variant_count():
    result = run_seed(
        BACKEND / "product_catalog.json",
        "sqlite:///:memory:",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "validated"
    assert report["source_brand_records"] == 61
    assert report["brands"] == 60
    assert report["fragrances"] == 1389
    assert report["variants"] == 512
    assert report["products_without_variants"] == 1062
    assert report["offers_imported"] == 0
    assert report["database_written"] is False


def test_dior_sauvage_edp_has_verified_100ml_variant():
    catalog = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
    product = next(row for row in catalog["products"] if row["product_id"] == "SH-AUTO-0178")
    assert product["brand_name"] == "Dior"
    assert product["canonical_name"] == "Sauvage"
    assert product["concentration"] == "Eau de Parfum"
    assert any("dior.com/fr_fr/beauty/products/sauvage-eau-de-parfum" in url
               for url in product["verification_sources"])
    variants = [row for row in catalog["variants"]
                if row["product_id"] == "SH-AUTO-0178" and row["size_ml"] == 100]
    assert len(variants) == 1
    assert variants[0]["variant_id"] == "VAR-9e1f0d0b8a3c6e42"
    assert variants[0]["gtins"] == []
    assert variants[0]["mpns"] == []
    assert variants[0]["canonical_key"] == "christian-dior|sauvage|edp|100|standard"


def test_real_catalog_seed_populates_every_legacy_map_and_is_idempotent(tmp_path):
    import sys

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    sys.path.insert(0, str(BACKEND))
    from app.models import LegacyProductIdMap, LegacyVariantIdMap, ProductVariant
    from app.services.ingestion_persistence import resolve_legacy_ids

    catalog_path = BACKEND / "product_catalog.json"
    raw_catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    products = raw_catalog["products"]
    variants = raw_catalog["variants"]
    database_path = tmp_path / "full-catalog.sqlite3"
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )
    assert migration.returncode == 0, migration.stderr

    first = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
    assert first.returncode == 0, first.stderr
    first_report = json.loads(first.stdout)
    assert first_report["status"] == "seeded"
    assert first_report["database_counts"]["legacy_product_id_map"] == len(products)
    assert first_report["database_counts"]["product_variants"] == len(variants)
    assert first_report["database_counts"]["legacy_variant_id_map"] == len(variants)

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            product_ids = set(session.scalars(select(LegacyProductIdMap.legacy_product_id)))
            variant_ids = set(session.scalars(select(LegacyVariantIdMap.legacy_variant_id)))
            assert product_ids == {str(row["product_id"]) for row in products}
            assert variant_ids == {str(row["variant_id"]) for row in variants}

            # Every product ID has a persisted fragrance UUID, including products
            # that intentionally have no declared variant.
            for legacy_product_id in product_ids:
                mapping = session.get(LegacyProductIdMap, legacy_product_id)
                assert mapping is not None and mapping.fragrance_id is not None

            # Every variant resolves together with its owning historical product ID.
            for variant in variants:
                resolved = resolve_legacy_ids(
                    session,
                    legacy_product_id=str(variant["product_id"]),
                    legacy_variant_id=str(variant["variant_id"]),
                )
                assert resolved is not None, (
                    f"unresolved legacy IDs: {variant['product_id']} / {variant['variant_id']}"
                )

            sauvage_mapping = resolve_legacy_ids(
                session,
                legacy_product_id="SH-AUTO-0178",
                legacy_variant_id="VAR-9e1f0d0b8a3c6e42",
            )
            assert sauvage_mapping is not None
            sauvage_variant = session.get(ProductVariant, sauvage_mapping.product_variant_id)
            assert sauvage_variant is not None
            assert sauvage_variant.canonical_key == "christian-dior|sauvage|edp|100|standard"
            assert sauvage_variant.fragrance.brand.normalized_name == "christian dior"

            first_product_id = str(products[0]["product_id"])
            missing_variant_id = "LEGACY-VARIANT-ID-DOES-NOT-EXIST"
            resolved_missing = resolve_legacy_ids(
                session,
                legacy_product_id=first_product_id,
                legacy_variant_id=missing_variant_id,
            )
            assert resolved_missing is None

        # Re-running the seed must be a no-op for both mapping tables.
        second = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
        assert second.returncode == 0, second.stderr
        second_report = json.loads(second.stdout)
        assert second_report["database_counts"]["legacy_product_id_map"] == len(products)
        assert second_report["database_counts"]["legacy_variant_id_map"] == len(variants)

        # Re-running the migration must preserve all rows and the target revision.
        migration_again = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "0002_ingestion_raw"],
            cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
        )
        assert migration_again.returncode == 0, migration_again.stderr
        with Session(engine) as session:
            assert session.scalar(select(LegacyProductIdMap.legacy_product_id).limit(1))
            assert session.scalar(select(LegacyVariantIdMap.legacy_variant_id).limit(1))
            assert len(list(session.scalars(select(LegacyProductIdMap)))) == len(products)
            assert len(list(session.scalars(select(LegacyVariantIdMap)))) == len(variants)
    finally:
        engine.dispose()



def test_bplatz_store_seed_is_idempotent_and_leaves_other_eight_stores_untouched(tmp_path):
    from sqlalchemy.orm import Session

    sys.path.insert(0, str(BACKEND))
    from app.models import Store

    catalog_path = BACKEND / "product_catalog.json"
    database_path = tmp_path / "stores-idempotency.sqlite3"
    database_url = f"sqlite:///{database_path}"
    env = os.environ.copy()
    env["SCENTHUNTER_CATALOG_DATABASE_URL"] = database_url
    env.pop("SCENTHUNTER_DATABASE_URL", None)

    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )
    assert migration.returncode == 0, migration.stderr

    other_stores = [
        ("deloox", "Deloox", "deloox.example", "NL", "EUR", "inactive"),
        ("parfumcity", "Parfumcity", "parfumcity.example", "DE", "EUR", "inactive"),
        ("parfumzentrum", "Parfumzentrum", "parfumzentrum.example", "DE", "EUR", "inactive"),
        ("perfumemarket", "Perfumemarket", "perfumemarket.example", "IT", "EUR", "inactive"),
        ("sabina", "Sabina", "sabina.example", "ES", "EUR", "inactive"),
        ("orioudh", "Orioudh", "orioudh.example", "FR", "EUR", "inactive"),
        ("easycosmetic", "Easycosmetic", "easycosmetic.example", "DE", "EUR", "inactive"),
        ("notino", "Notino", "notino.example", "CZ", "EUR", "inactive"),
    ]
    engine = create_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            for slug, name, domain, country, currency, status in other_stores:
                session.add(Store(
                    name=name, slug=slug, domain=domain, country=country,
                    currency=currency, status=status,
                ))
        with Session(engine) as session:
            before = {
                row.slug: (row.name, row.domain, row.country, row.currency, row.status)
                for row in session.scalars(select(Store)).all()
            }
        assert set(before) == {row[0] for row in other_stores}

        first = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
        assert first.returncode == 0, first.stderr
        second = run_seed(catalog_path, database_url, "--apply", "--seed-bplatz-store")
        assert second.returncode == 0, second.stderr

        with Session(engine) as session:
            rows = session.scalars(select(Store)).all()
            by_slug = {row.slug: row for row in rows}
            assert len(rows) == 9
            assert set(by_slug) == set(before) | {"bplatz"}
            for slug, expected in before.items():
                row = by_slug[slug]
                assert (row.name, row.domain, row.country, row.currency, row.status) == expected
            bplatz = by_slug["bplatz"]
            assert (bplatz.name, bplatz.domain, bplatz.country, bplatz.currency, bplatz.status) == (
                "Bplatz", "bplatz.de", "DE", "EUR", "active",
            )
    finally:
        engine.dispose()

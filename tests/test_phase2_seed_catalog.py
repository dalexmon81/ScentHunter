from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


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
    assert report["brands"] == 1
    assert report["fragrances"] == 2
    assert report["variants"] == 1
    assert report["products_without_variants"] == 1
    assert report["offers_imported"] == 0
    assert report["database_written"] is False
    assert not (tmp_path / "unused.sqlite3").exists()


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

    result = run_seed(catalog_path, database_url, "--apply")
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
    assert report["variants"] == 511
    assert report["products_without_variants"] == 1063
    assert report["offers_imported"] == 0
    assert report["database_written"] is False

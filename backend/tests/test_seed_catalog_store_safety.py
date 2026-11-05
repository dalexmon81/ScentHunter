"""Safety contract for canonical catalog seeding and retailer activation."""
from __future__ import annotations

import json
import subprocess
import sys
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


def test_dior_pilot_dry_run_is_scoped_and_does_not_activate_a_store():
    report = run_seed("--product-id", "SH-AUTO-0178")
    assert report["status"] == "validated"
    assert report["product_filter"] == ["SH-AUTO-0178"]
    assert report["brands"] == 1
    assert report["fragrances"] == 1
    assert report["variants"] == 1
    assert report["products_without_variants"] == 0
    assert report["stores_to_seed"] == []
    assert report["offers_imported"] == 0
    assert report["database_written"] is False
    assert report["source_modified"] is False

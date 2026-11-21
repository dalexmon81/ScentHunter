"""Safety contract for the isolated API-only pilot startup mode."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import main
from fastapi.testclient import TestClient


def test_api_only_mode_skips_automatic_catalog_discovery_and_hydration():
    with patch.dict(os.environ, {"SCENTHUNTER_DISABLE_AUTOMATIC_CATALOG_STARTUP": "1"}, clear=True):
        with (
            patch.object(main, "_CATALOG_BOOTSTRAP_STARTED", False),
            patch.object(main, "_catalog_is_ready") as catalog_ready,
            patch.object(main, "_stores_missing_catalog") as missing_stores,
            patch.object(main, "_start_catalog_hydration") as hydration,
            patch.object(main, "_start_catalog_discovery") as discovery,
            patch.object(main.threading, "Thread") as thread,
        ):
            main._start_catalog_bootstrap()

    catalog_ready.assert_not_called()
    missing_stores.assert_not_called()
    hydration.assert_not_called()
    discovery.assert_not_called()
    thread.assert_not_called()


def test_api_only_mode_skips_phase0_queue_schema_initialization():
    fake_module = types.ModuleType("scenthunter_next_engine.phase0_baseline_jobs")
    fake_module.connect = Mock()
    fake_module.ensure_schema = Mock()
    fake_module.ensure_smoke_schema = Mock()

    with patch.dict(os.environ, {"SCENTHUNTER_DISABLE_AUTOMATIC_CATALOG_STARTUP": "1"}, clear=True):
        with patch.dict(sys.modules, {"scenthunter_next_engine.phase0_baseline_jobs": fake_module}):
            main._initialize_phase0_baseline_jobs()

    fake_module.connect.assert_not_called()
    fake_module.ensure_schema.assert_not_called()
    fake_module.ensure_smoke_schema.assert_not_called()


def test_default_mode_preserves_existing_catalog_startup_behavior():
    with patch.dict(os.environ, {}, clear=True):
        with (
            patch.object(main, "_CATALOG_BOOTSTRAP_STARTED", False),
            patch.object(main, "_CATALOG_BOOTSTRAP_DONE", False),
            patch.object(main, "_catalog_is_ready", return_value=True),
            patch.object(main, "_stores_missing_catalog", return_value=[]),
            patch.object(main, "_start_catalog_hydration") as hydration,
            patch.object(main, "_start_catalog_discovery") as discovery,
        ):
            main._start_catalog_bootstrap()

    hydration.assert_called_once()
    discovery.assert_called_once()


def test_pilot_container_runs_api_without_starting_ingestion_worker():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile.pilot").read_text()
    staging = (root / "fly.staging.toml").read_text()

    assert "SCENTHUNTER_DISABLE_AUTOMATIC_CATALOG_STARTUP=1" in dockerfile
    assert "app.workers.sqlite_worker" not in dockerfile
    assert "exec /app/.venv/bin/uvicorn main:app" in dockerfile
    assert 'SCENTHUNTER_DISABLE_AUTOMATIC_CATALOG_STARTUP = "1"' in staging


def test_api_only_mode_rejects_manual_legacy_scraping_and_worker_triggers():
    client = TestClient(main.app)
    blocked_requests = [
        ("GET", "/search?q=Hawas"),
        ("GET", "/search-start?q=Hawas"),
        ("GET", "/catalog/resync-easycosmetic"),
        ("GET", "/catalog/resync-deloox"),
        ("GET", "/catalog/resync-sabina-deloox"),
        ("GET", "/diagnostic/matcher?store=deloox&q=Hawas"),
        ("GET", "/diagnostic/store-pipeline?store=notino&q=Hawas&probe=true"),
        ("GET", "/diagnostic/scraper-offer-compare?store=deloox&q=Hawas&url=https%3A%2F%2Fwww.deloox.com%2Fproduct%2F123"),
        ("GET", "/diagnose-catalog-live-parse?store=deloox&url=https%3A%2F%2Fwww.deloox.com%2Fproduct%2F123"),
        ("GET", "/diagnose-hawas-ice-offers-read-only"),
        ("POST", "/admin/phase0/baseline/start"),
        ("POST", "/admin/phase0/smoke/start"),
        ("POST", "/admin/phase0/admin/resume-deloox-queue"),
    ]

    with patch.dict(os.environ, {"SCENTHUNTER_DISABLE_AUTOMATIC_CATALOG_STARTUP": "1"}, clear=True):
        for method, path in blocked_requests:
            response = client.request(method, path)
            assert response.status_code == 503, (method, path, response.status_code, response.text)
            assert "disabled in API-only pilot mode" in response.json()["detail"]

        health = client.get("/health")
        assert health.status_code == 200

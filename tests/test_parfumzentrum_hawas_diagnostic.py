"""Regression tests for the read-only Parfum-Zentrum catalog diagnostic."""

from pathlib import Path


def test_parfumzentrum_hawas_diagnostic_supports_hawas_ice_target():
    source = Path("backend/diagnose_parfumzentrum_hawas_gap.py").read_text(encoding="utf-8")
    assert 'if "ice" in lowered:' in source
    assert '"hawas_ice"' in source
    assert '"913265"' in source
    assert '"614514331040"' in source
    assert "base_product_rows" in source
    assert "hydration_queue" in source
    assert "catalog_search_fts" in source
    assert 'uri=True' in source
    assert 'PRAGMA query_only=ON' in source
    assert '"database_written": False' in source
    assert '"network": False' in source

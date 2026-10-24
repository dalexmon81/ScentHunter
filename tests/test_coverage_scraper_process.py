"""Regression tests for isolated scraper coverage subprocess diagnostics."""

from backend.catalog_engine import _coverage_scraper_process


def test_coverage_subprocess_preserves_scraper_import_error(monkeypatch):
    import backend.catalog_engine as catalog_engine

    monkeypatch.setattr(catalog_engine, "_foreground_search_running", lambda: False)
    result = _coverage_scraper_process(
        "scenthunter_missing_test_scraper_000",
        ["test query"],
        timeout_seconds=5,
    )

    assert result["ok"] is False
    assert result["reports"] == []
    assert result["error"].startswith("ModuleNotFoundError:")
    assert "scenthunter_missing_test_scraper_000" in result["error"]


def test_coverage_subprocess_reports_scraper_without_search_entrypoint(monkeypatch):
    import backend.catalog_engine as catalog_engine

    monkeypatch.setattr(catalog_engine, "_foreground_search_running", lambda: False)
    result = _coverage_scraper_process(
        "json",
        ["test query"],
        timeout_seconds=5,
    )

    assert result["ok"] is False
    assert result["reports"] == []
    assert result["error"] == "RuntimeError:scraper_search_unavailable"

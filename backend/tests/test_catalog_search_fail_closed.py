"""User-facing catalog search must never fall back to live retailer adapters."""

import main


def test_missing_catalog_engine_fails_closed_without_starting_retailer_search(monkeypatch):
    monkeypatch.setattr(main, "CATALOG_ENGINE_AVAILABLE", False)
    monkeypatch.setattr(main, "catalog_search_local", None)

    def forbidden_live_search(*args, **kwargs):
        raise AssertionError("user search must not start retailer adapters")

    monkeypatch.setattr(main, "_run_controlled_store", forbidden_live_search)

    reports = main.collect_store_reports_isolated("Sauvage", ["notino", "deloox"])

    assert [row["store"] for row in reports] == ["notino", "deloox"]
    assert all(row["status"] == "error" for row in reports)
    assert all(row["error"] == "catalog_engine_unavailable" for row in reports)
    assert all(row["verified"] is False for row in reports)
    assert all(row["details"]["source"] == "persistent_catalog" for row in reports)


def test_catalog_search_ignores_legacy_live_fallback_override(monkeypatch):
    monkeypatch.setattr(main, "CATALOG_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(main, "catalog_search_local", lambda *args, **kwargs: [])

    captured = {}

    def catalog_only(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(main, "_collect_catalog_reports_isolated", catalog_only)

    main.collect_store_reports_isolated(
        "Sauvage",
        ["notino"],
        allow_live_fallback=True,
    )

    assert captured["allow_live_fallback"] is False

"""Regression tests for the user-facing legacy search fail-closed boundary."""

import main as scent_hunter


def test_user_search_forces_live_fallback_off(monkeypatch):
    captured = {}

    monkeypatch.setattr(scent_hunter, "CATALOG_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(scent_hunter, "catalog_search_local", lambda *args, **kwargs: [])

    def catalog_only(*args, **kwargs):
        captured.update(kwargs)
        return [{"store": "fixture-store", "status": "ok", "results": []}]

    monkeypatch.setattr(scent_hunter, "_collect_catalog_reports_isolated", catalog_only)

    reports = scent_hunter.collect_store_reports_isolated(
        "Dior Sauvage",
        ["fixture-store"],
        allow_live_fallback=True,
    )

    assert captured["allow_live_fallback"] is False
    assert reports[0]["store"] == "fixture-store"


def test_user_search_fails_closed_when_catalog_engine_is_unavailable(monkeypatch):
    def forbidden_live_adapter(*args, **kwargs):
        raise AssertionError("user search must never start a live retailer adapter")

    monkeypatch.setattr(scent_hunter, "CATALOG_ENGINE_AVAILABLE", False)
    monkeypatch.setattr(scent_hunter, "_run_controlled_store", forbidden_live_adapter)

    reports = scent_hunter.collect_store_reports_isolated(
        "Dior Sauvage",
        ["fixture-store"],
        allow_live_fallback=True,
    )

    assert len(reports) == 1
    assert reports[0]["status"] == "error"
    assert reports[0]["verified"] is False
    assert reports[0]["details"]["source"] == "persistent_catalog"
    assert reports[0]["error"] == "catalog_engine_unavailable"

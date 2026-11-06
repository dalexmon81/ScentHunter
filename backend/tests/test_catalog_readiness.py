from app.services.catalog_readiness import (
    catalog_has_indexed_store,
    stores_missing_indexed_catalog,
)


def test_any_configured_store_can_make_catalog_ready():
    statuses = {"deloox": {"valid_indexed_urls": 3}}
    assert catalog_has_indexed_store(statuses, ["sabina", "deloox"]) is True


def test_one_populated_store_does_not_hide_missing_retailers():
    statuses = {
        "sabina": {"valid_indexed_urls": 12},
        "deloox": {"valid_indexed_urls": 0},
    }
    assert stores_missing_indexed_catalog(statuses, ["sabina", "deloox"]) == ["deloox"]


def test_legacy_indexed_urls_field_remains_supported():
    assert catalog_has_indexed_store({"bplatz": {"indexed_urls": "2"}}, ["bplatz"])
    assert stores_missing_indexed_catalog({"bplatz": {"indexed_urls": "0"}}, ["bplatz"]) == ["bplatz"]


def test_invalid_and_missing_counts_fail_closed():
    statuses = {"sabina": {"valid_indexed_urls": "unknown"}}
    assert catalog_has_indexed_store(statuses, ["sabina"]) is False
    assert stores_missing_indexed_catalog(statuses, ["sabina", "deloox"]) == ["sabina", "deloox"]


def test_empty_registry_is_not_ready():
    assert catalog_has_indexed_store({}, []) is False
    assert stores_missing_indexed_catalog({}, []) == []

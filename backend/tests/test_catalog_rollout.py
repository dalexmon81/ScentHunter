from app.services.catalog_rollout import (
    catalog_rollout_decision,
    compare_search_payloads,
)


def test_catalog_rollout_is_disabled_by_default():
    decision = catalog_rollout_decision("Sauvage", environ={})
    assert decision["enabled"] is False
    assert decision["traffic_percent"] == 0
    assert decision["use_catalog"] is False
    assert decision["run_shadow"] is False


def test_master_switch_defaults_to_full_catalog_only_when_enabled():
    decision = catalog_rollout_decision(
        "Sauvage",
        "cohort-1",
        environ={"SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1"},
    )
    assert decision["traffic_percent"] == 100
    assert decision["use_catalog"] is True
    assert decision["run_shadow"] is False


def test_canary_percentage_is_deterministic_for_a_stable_key():
    env = {
        "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1",
        "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "25",
    }
    first = catalog_rollout_decision("Sauvage", "session-123", environ=env)
    second = catalog_rollout_decision("Sauvage", "session-123", environ=env)
    assert first == second
    assert 0 <= first["bucket"] < 100
    assert first["use_catalog"] is (first["bucket"] < 25)


def test_invalid_or_disabled_percentage_fails_closed():
    disabled = catalog_rollout_decision(
        "Sauvage",
        environ={
            "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "0",
            "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "100",
        },
    )
    invalid = catalog_rollout_decision(
        "Sauvage",
        environ={
            "SCENTHUNTER_CATALOG_SEARCH_ENABLED": "1",
            "SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT": "not-a-number",
        },
    )
    assert disabled["use_catalog"] is False
    assert invalid["traffic_percent"] == 0
    assert invalid["use_catalog"] is False


def test_shadow_mode_reads_catalog_without_selecting_catalog_response():
    decision = catalog_rollout_decision(
        "Sauvage",
        "session-123",
        environ={"SCENTHUNTER_CATALOG_SEARCH_SHADOW": "1"},
    )
    assert decision["run_shadow"] is True
    assert decision["use_catalog"] is False


def test_shadow_comparison_reports_product_and_offer_overlap():
    legacy = [
        {
            "brand": "Dior",
            "name": "Sauvage",
            "offers": [
                {"store": "notino", "url": "https://shop.invalid/a/", "currency": "EUR"},
                {"store": "deloox", "url": "https://shop.invalid/b", "currency": "EUR"},
            ],
        }
    ]
    catalog = {
        "results": [
            {
                "canonical_brand": "Dior",
                "canonical_name": "Sauvage",
                "offers": [
                    {"store": "notino", "url": "https://shop.invalid/a", "currency": "EUR"},
                    {"store": "sabina", "url": "https://shop.invalid/c", "currency": "EUR"},
                ],
            }
        ]
    }

    comparison = compare_search_payloads(legacy, catalog)
    assert comparison["status"] == "compared"
    assert comparison["shared_product_count"] == 1
    assert comparison["legacy_only_product_count"] == 0
    assert comparison["catalog_only_product_count"] == 0
    assert comparison["shared_offer_count"] == 1
    assert comparison["legacy_only_offer_count"] == 1
    assert comparison["catalog_only_offer_count"] == 1
    assert comparison["product_overlap_ratio"] == 1.0
    assert comparison["offer_overlap_ratio"] == 0.3333

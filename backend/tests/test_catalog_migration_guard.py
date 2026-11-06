from app.services.catalog_migration_guard import (
    compare_search_results,
    evaluate_rollout_gate,
)


def test_shadow_compare_detects_missing_and_additional_without_cross_currency_match():
    legacy = [
        {"canonical_key": "dior|sauvage|edp|100", "store": "notino", "currency": "EUR", "price": 99.9},
        {"canonical_key": "dior|sauvage|edp|100", "store": "store-b", "currency": "GBP", "price": 80},
    ]
    catalog = [
        {"canonical_key": "dior|sauvage|edp|100", "store": "notino", "currency": "EUR", "price": 99.9},
        {"canonical_key": "dior|sauvage|edp|100", "store": "store-b", "currency": "EUR", "price": 80},
    ]

    result = compare_search_results(legacy, catalog)

    assert result["missing_from_catalog"] == 1
    assert result["additional_in_catalog"] == 1
    assert result["result_mismatch_rate"] == 1.0
    assert result["currency_isolation"] is True


def test_shadow_compare_reports_price_drift_separately():
    legacy = [{
        "canonical_key": "dior|sauvage|edp|100",
        "store": "notino",
        "currency": "EUR",
        "price": "99.90",
    }]
    catalog = [{
        "canonical_key": "dior|sauvage|edp|100",
        "store": "notino",
        "currency": "EUR",
        "price": "101.00",
    }]

    result = compare_search_results(legacy, catalog)

    assert result["result_mismatch_rate"] == 0
    assert result["price_checks"] == 1
    assert result["price_mismatches"] == 1
    assert result["price_mismatch_rate"] == 1.0


def test_rollout_gate_holds_until_minimum_shadow_sample_and_quality_thresholds():
    result = evaluate_rollout_gate(
        sample_count=80,
        result_mismatch_rate=0,
        error_rate=0,
        stale_offer_rate=0,
        legacy_p95_ms=100,
        catalog_p95_ms=90,
        current_stage_percent=0,
    )

    assert result["decision"] == "hold"
    assert result["recommended_stage_percent"] == 0
    assert "insufficient_shadow_samples" in result["reasons"]
    assert result["traffic_change_performed"] is False


def test_rollout_gate_recommends_only_one_increment_after_clean_evidence():
    result = evaluate_rollout_gate(
        sample_count=1000,
        result_mismatch_rate=0.002,
        error_rate=0.001,
        stale_offer_rate=0.01,
        legacy_p95_ms=100,
        catalog_p95_ms=110,
        current_stage_percent=5,
    )

    assert result["decision"] == "advance_recommended"
    assert result["recommended_stage_percent"] == 20
    assert result["traffic_change_performed"] is False


def test_rollout_gate_recommends_rollback_on_critical_regression():
    result = evaluate_rollout_gate(
        sample_count=1000,
        result_mismatch_rate=0.08,
        error_rate=0.03,
        stale_offer_rate=0.01,
        legacy_p95_ms=100,
        catalog_p95_ms=250,
        current_stage_percent=50,
    )

    assert result["decision"] == "rollback_recommended"
    assert result["recommended_stage_percent"] == 0
    assert len(result["reasons"]) >= 3
    assert result["traffic_change_performed"] is False

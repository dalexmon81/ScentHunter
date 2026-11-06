"""Deterministic shadow comparison and rollout safety gates.

This module computes decisions from supplied telemetry. It does not route traffic,
change feature flags, call retailers, or deploy anything.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


ROLLOUT_STAGES = (5, 20, 50, 100)


def _price(value) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _key(row: Mapping) -> tuple[str, str, str]:
    return (
        str(row.get("canonical_key") or "").strip().lower(),
        str(row.get("store") or "").strip().lower(),
        str(row.get("currency") or "").strip().upper(),
    )


def compare_search_results(
    legacy_results: Iterable[Mapping],
    catalog_results: Iterable[Mapping],
    *,
    price_tolerance: Decimal = Decimal("0.01"),
) -> dict:
    """Compare two result sets without treating different currencies as equal."""
    legacy = [dict(row) for row in legacy_results]
    catalog = [dict(row) for row in catalog_results]
    legacy_counts = Counter(_key(row) for row in legacy)
    catalog_counts = Counter(_key(row) for row in catalog)

    missing = sum((legacy_counts - catalog_counts).values())
    additional = sum((catalog_counts - legacy_counts).values())
    comparable = min(len(legacy), len(catalog))
    mismatches = missing + additional

    legacy_by_key: dict[tuple[str, str, str], list[dict]] = {}
    catalog_by_key: dict[tuple[str, str, str], list[dict]] = {}
    for row in legacy:
        legacy_by_key.setdefault(_key(row), []).append(row)
    for row in catalog:
        catalog_by_key.setdefault(_key(row), []).append(row)

    price_checks = 0
    price_mismatches = 0
    for key in legacy_by_key.keys() & catalog_by_key.keys():
        old_rows = legacy_by_key[key]
        new_rows = catalog_by_key[key]
        for old, new in zip(old_rows, new_rows):
            old_price = _price(old.get("price"))
            new_price = _price(new.get("price"))
            if old_price is None or new_price is None:
                price_mismatches += 1
                continue
            price_checks += 1
            if abs(old_price - new_price) > price_tolerance:
                price_mismatches += 1

    denominator = max(len(legacy), len(catalog), 1)
    return {
        "legacy_count": len(legacy),
        "catalog_count": len(catalog),
        "missing_from_catalog": missing,
        "additional_in_catalog": additional,
        "result_mismatch_rate": round(mismatches / denominator, 6),
        "price_checks": price_checks,
        "price_mismatches": price_mismatches,
        "price_mismatch_rate": round(
            price_mismatches / max(price_checks + price_mismatches, 1), 6
        ),
        "currency_isolation": True,
    }


def evaluate_rollout_gate(
    *,
    sample_count: int,
    result_mismatch_rate: float,
    error_rate: float,
    stale_offer_rate: float,
    legacy_p95_ms: float,
    catalog_p95_ms: float,
    current_stage_percent: int = 0,
) -> dict:
    """Return a safe next-stage recommendation; never performs a rollout."""
    if current_stage_percent not in (0, *ROLLOUT_STAGES):
        raise ValueError("unsupported_rollout_stage")

    values = (
        sample_count,
        result_mismatch_rate,
        error_rate,
        stale_offer_rate,
        legacy_p95_ms,
        catalog_p95_ms,
    )
    if any(value is None for value in values):
        raise ValueError("all_gate_metrics_are_required")
    if sample_count < 0 or any(
        rate < 0 or rate > 1
        for rate in (result_mismatch_rate, error_rate, stale_offer_rate)
    ):
        raise ValueError("invalid_gate_metrics")
    if legacy_p95_ms < 0 or catalog_p95_ms < 0:
        raise ValueError("latency_must_be_non_negative")

    latency_ratio = (
        catalog_p95_ms / legacy_p95_ms if legacy_p95_ms > 0
        else (0.0 if catalog_p95_ms == 0 else float("inf"))
    )
    rollback_reasons = []
    if error_rate > 0.02:
        rollback_reasons.append("error_rate_over_2_percent")
    if result_mismatch_rate > 0.05:
        rollback_reasons.append("result_mismatch_over_5_percent")
    if stale_offer_rate > 0.20:
        rollback_reasons.append("stale_offer_rate_over_20_percent")
    if latency_ratio > 2.0:
        rollback_reasons.append("catalog_p95_over_2x_legacy")

    if rollback_reasons:
        return {
            "decision": "rollback_recommended",
            "current_stage_percent": current_stage_percent,
            "recommended_stage_percent": 0,
            "latency_ratio": round(latency_ratio, 4),
            "reasons": rollback_reasons,
            "traffic_change_performed": False,
        }

    blockers = []
    if sample_count < 100:
        blockers.append("insufficient_shadow_samples")
    if result_mismatch_rate > 0.01:
        blockers.append("result_mismatch_over_1_percent")
    if error_rate > 0.005:
        blockers.append("error_rate_over_0_5_percent")
    if stale_offer_rate > 0.05:
        blockers.append("stale_offer_rate_over_5_percent")
    if latency_ratio > 1.25:
        blockers.append("catalog_p95_over_1_25x_legacy")

    if blockers:
        return {
            "decision": "hold",
            "current_stage_percent": current_stage_percent,
            "recommended_stage_percent": current_stage_percent,
            "latency_ratio": round(latency_ratio, 4),
            "reasons": blockers,
            "traffic_change_performed": False,
        }

    next_stage = next(
        (stage for stage in ROLLOUT_STAGES if stage > current_stage_percent),
        100,
    )
    return {
        "decision": "advance_recommended" if next_stage > current_stage_percent else "maintain",
        "current_stage_percent": current_stage_percent,
        "recommended_stage_percent": next_stage,
        "latency_ratio": round(latency_ratio, 4),
        "reasons": [],
        "traffic_change_performed": False,
    }

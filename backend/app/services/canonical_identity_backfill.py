"""Dry-run-only planner for legacy catalog canonical identity backfills.

This module performs no database access and never writes or merges catalog rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

from app.services.product_normalization import (
    NormalizedProduct,
    normalize_gtin,
    normalize_product,
)


@dataclass(frozen=True)
class BackfillRowPlan:
    source_reference: str | None
    status: str
    normalized: NormalizedProduct | None
    gtin: str | None
    reason: str | None = None


@dataclass(frozen=True)
class BackfillPreview:
    rows: tuple[BackfillRowPlan, ...]
    ready_count: int
    review_count: int
    invalid_count: int


def preview_canonical_backfill(
    records: Iterable[Mapping[str, Any]],
) -> BackfillPreview:
    """Normalize legacy rows into a reviewable preview without persistence."""
    plans: list[BackfillRowPlan] = []
    seen_keys: dict[str, str | None] = {}
    for index, record in enumerate(records):
        source = record.get("id") or record.get("source_reference") or f"row:{index}"
        try:
            product = normalize_product(
                str(record.get("brand") or ""),
                str(record.get("title") or ""),
                concentration=record.get("concentration"),
                size_ml=record.get("size_ml"),
                packaging=record.get("packaging"),
            )
        except (TypeError, ValueError) as exc:
            plans.append(BackfillRowPlan(str(source), "invalid", None, None, str(exc)))
            continue

        raw_gtin = record.get("gtin")
        gtin = normalize_gtin(raw_gtin)
        if raw_gtin not in (None, "") and gtin is None:
            plans.append(
                BackfillRowPlan(str(source), "review", product, None,
                                "invalid_gtin_requires_review")
            )
            continue

        previous = seen_keys.get(product.canonical_key, gtin)
        if product.canonical_key in seen_keys and previous != gtin:
            plans.append(
                BackfillRowPlan(str(source), "review", product, gtin,
                                "duplicate_canonical_key_gtin_conflict")
            )
            continue
        seen_keys[product.canonical_key] = gtin
        plans.append(BackfillRowPlan(str(source), "ready", product, gtin))

    return BackfillPreview(
        rows=tuple(plans),
        ready_count=sum(row.status == "ready" for row in plans),
        review_count=sum(row.status == "review" for row in plans),
        invalid_count=sum(row.status == "invalid" for row in plans),
    )

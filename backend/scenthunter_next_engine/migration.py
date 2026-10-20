"""Read-only-input migration helpers for an explicitly supplied legacy snapshot."""
from __future__ import annotations
from collections.abc import Iterable, Mapping
from typing import Any

from .legacy_bridge import observation_from_legacy_rows
from .repository import SQLiteOfferRepository


def import_legacy_snapshot(rows: Iterable[Mapping[str, Any]], repository: SQLiteOfferRepository) -> dict[str, Any]:
    """Import paired legacy rows into the next DB only; never opens legacy DB.

    Each input record contains `store`, `product_row`, and optional `variant_row`.
    Invalid rows are rejected with a reason and do not abort other records.
    """
    imported = 0
    replayed = 0
    rejected: list[dict[str, Any]] = []
    processed = 0
    for index, entry in enumerate(rows):
        processed += 1
        store = str(entry.get("store") or "").strip().casefold()
        product_row = entry.get("product_row")
        variant_row = entry.get("variant_row")
        source_url = ""
        variant_mapping = variant_row if isinstance(variant_row, Mapping) else {}
        if isinstance(product_row, Mapping):
            source_url = str(variant_mapping.get("variant_url") or variant_mapping.get("url") or product_row.get("url") or "")
        try:
            if not store or not isinstance(product_row, Mapping):
                raise ValueError("entry requires store and product_row mapping")
            observation = observation_from_legacy_rows(
                store=store,
                product_row=product_row,
                variant_row=variant_row if isinstance(variant_row, Mapping) else None,
                trace_id="legacy-snapshot-v1",
                parser_version="legacy-row-v1",
            )
            if repository.save_observation(observation):
                imported += 1
            else:
                replayed += 1
        except Exception as exc:
            rejected.append({
                "index": index,
                "store": store or None,
                "url": source_url or None,
                "error": f"{type(exc).__name__}: {exc}"[:1000],
            })
    return {
        "processed": processed,
        "imported": imported,
        "replayed": replayed,
        "rejected_count": len(rejected),
        "rejected": rejected[:200],
        "target_counts": repository.counts(),
    }

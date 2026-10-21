"""Fail-closed importer for explicitly supplied legacy candidate rows.

Validation is completed before the first repository write. API and CLI should
construct candidates with migration_plan.build_entries and run the same preflight.
This module never opens the legacy database or makes network requests.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .migration_plan import preflight_entries
from .repository import SQLiteOfferRepository


def import_legacy_snapshot(
    rows: Iterable[Mapping[str, Any]],
    repository: SQLiteOfferRepository,
    *,
    batch_size: int = 500,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> dict[str, Any]:
    """Validate every candidate before writing; reject the whole batch on any issue.

    Pairing-level quarantine must be supplied by the caller and checked before
    invoking this function. A rejected report performs zero writes.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if not callable(getattr(repository, "save_observations_batch", None)):
        raise RuntimeError("SQLiteOfferRepository.save_observations_batch is required")

    entries = list(rows)
    report = preflight_entries(entries)
    quarantine = report["_quarantine"]
    accepted = report["_accepted"]
    non_products = [q for q in quarantine if q.get("class") == "NON_PRODUCT_CONFIRMED"]
    blocking = [q for q in quarantine if q.get("class") != "NON_PRODUCT_CONFIRMED"]
    if blocking or not accepted or len(accepted) + len(non_products) != len(entries):
        return {
            "processed": len(entries), "imported": 0, "replayed": 0,
            "skipped_count": len(non_products), "rejected_count": len(blocking),
            "rejected": blocking, "quarantine": quarantine,
            "preflight": {k: v for k, v in report.items() if not k.startswith("_")},
            "target_counts": repository.counts(), "writes_started": False,
        }

    observations = [item["observation"] for item in accepted]
    # One repository call means the repository can commit/roll back the whole
    # candidate set in one SQLite transaction; chunking here could leave a partial
    # staging DB if a later batch failed.
    imported = repository.save_observations_batch(observations) if observations else 0
    replayed = len(observations) - imported
    if progress_callback:
        try:
            progress_callback(len(observations), imported, 0)
        except Exception:
            pass

    return {
        "processed": len(entries), "imported": imported, "replayed": replayed,
        "skipped_count": len(non_products), "rejected_count": 0, "rejected": [],
        "quarantine": non_products,
        "preflight": {k: v for k, v in report.items() if not k.startswith("_")},
        "target_counts": repository.counts(), "writes_started": bool(observations),
    }

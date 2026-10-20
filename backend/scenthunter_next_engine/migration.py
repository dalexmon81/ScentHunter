"""Read-only-input migration helpers for an explicitly supplied legacy snapshot."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlparse

from .legacy_bridge import observation_from_legacy_rows
from .repository import SQLiteOfferRepository


def _is_unpriced_category(entry: Mapping[str, Any]) -> bool:
    """Identify obvious category/listing URLs that have no offer price.

    These rows are navigation pages, not sellable offers. Skip only when the
    URL path explicitly identifies a category and neither paired row has a
    price, so genuine priced products are never discarded by this rule.
    """
    product_row = entry.get("product_row")
    variant_row = entry.get("variant_row")
    if not isinstance(product_row, Mapping):
        return False
    variant = variant_row if isinstance(variant_row, Mapping) else {}
    url = str(variant.get("variant_url") or variant.get("url") or product_row.get("url") or "")
    path = urlparse(url).path.casefold()
    category_path = any(part in path.split("/") for part in ("kategorie", "category", "categories", "categorie", "categorias"))
    if not category_path:
        return False
    price = variant.get("price")
    if price in (None, ""):
        price = product_row.get("price")
    return price in (None, "")


def import_legacy_snapshot(
    rows: Iterable[Mapping[str, Any]],
    repository: SQLiteOfferRepository,
    *,
    batch_size: int = 500,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> dict[str, Any]:
    """Import paired legacy rows into the next DB only; never opens the legacy DB.

    Obvious unpriced category/listing pages are skipped, since they are not
    sellable offers. Other invalid rows are reported and cause staging
    validation to fail at the API layer. No legacy data is modified.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if not callable(getattr(repository, "save_observations_batch", None)):
        raise RuntimeError(
            "SQLiteOfferRepository.save_observations_batch is required; deploy the matching repository.py optimization before migration"
        )

    imported = 0
    replayed = 0
    skipped = 0
    rejected: list[dict[str, Any]] = []
    processed = 0
    batch = []

    def flush_batch() -> None:
        nonlocal imported, replayed, batch
        if not batch:
            return
        newly_saved = repository.save_observations_batch(batch)
        imported += newly_saved
        replayed += len(batch) - newly_saved
        batch = []

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
            if _is_unpriced_category(entry):
                skipped += 1
                continue
            observation = observation_from_legacy_rows(
                store=store,
                product_row=product_row,
                variant_row=variant_row if isinstance(variant_row, Mapping) else None,
                trace_id="legacy-snapshot-v1",
                parser_version="legacy-row-v1",
            )
            batch.append(observation)
            if len(batch) >= batch_size:
                flush_batch()
        except Exception as exc:
            rejected.append({"index": index, "store": store or None, "url": source_url or None, "error": f"{type(exc).__name__}: {exc}"[:1000]})
        if progress_callback and (processed % batch_size == 0 or processed == 1):
            try:
                progress_callback(processed, imported, len(rejected))
            except Exception:
                pass

    flush_batch()
    if progress_callback:
        try:
            progress_callback(processed, imported, len(rejected))
        except Exception:
            pass

    return {
        "processed": processed,
        "imported": imported,
        "replayed": replayed,
        "skipped_count": skipped,
        "rejected_count": len(rejected),
        "rejected": rejected[:200],
        "target_counts": repository.counts(),
    }

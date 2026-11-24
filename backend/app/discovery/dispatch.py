"""Shared dispatch of discovered retailer references into background fetch jobs.

This module owns discovery pagination/dispatch policy only. It does not perform
retailer I/O, canonical matching, database writes or offer publication.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence
from uuid import UUID

from app.connectors.base import DiscoveredProduct


@dataclass(frozen=True)
class DiscoveryDispatchResult:
    fetch_jobs_queued: int
    next_cursor: str | None
    errors: tuple[str, ...]


def dispatch_discovered_products(
    store_id: UUID,
    products: Sequence[DiscoveredProduct],
    *,
    cursor: str | None,
    limit: int,
    enqueue_fetch: Callable[[UUID, str], Any],
    enqueue_next_page: Callable[..., Any],
) -> DiscoveryDispatchResult:
    """Queue every discovered reference and continue pagination when a page is full.

    Matching is deliberately not performed here. Every candidate proceeds to
    the shared fetch/offer ingestion gate, where canonical identity is resolved.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if cursor is not None and not str(cursor).isdigit():
        raise ValueError("cursor must be a non-negative integer")

    queued = 0
    errors: list[str] = []
    for product in products:
        try:
            enqueue_fetch(store_id, product.external_product_id)
            queued += 1
        except Exception as exc:
            errors.append(
                f"enqueue_fetch:{product.external_product_id}:{type(exc).__name__}:{exc}"
            )

    next_cursor = None
    if len(products) == limit:
        next_cursor = str(int(cursor or 0) + len(products))
        try:
            enqueue_next_page(store_id, cursor=next_cursor, limit=limit)
        except Exception as exc:
            errors.append(f"enqueue_next_page:{type(exc).__name__}:{exc}")

    return DiscoveryDispatchResult(
        fetch_jobs_queued=queued,
        next_cursor=next_cursor,
        errors=tuple(errors),
    )

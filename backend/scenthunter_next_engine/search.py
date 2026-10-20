"""Read-only search service for the isolated ScentHunter next engine.

This service only reads the next-engine repository. It never scrapes, triggers
hydration, or writes to the legacy catalog.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .repository import SQLiteOfferRepository


def _fold(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(c for c in raw if not unicodedata.combining(c)).split())


@dataclass(frozen=True)
class SearchRequest:
    query: str
    store: str | None = None
    currency: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if self.currency:
            from .models import normalize_currency
            try:
                normalize_currency(self.currency)
            except ValueError as exc:
                raise ValueError("currency must be a recognized ISO 4217 code") from exc


class SearchService:
    """Small deterministic read model; API handlers should remain thin."""

    def __init__(self, repository: SQLiteOfferRepository):
        self.repository = repository

    def search(self, request: SearchRequest) -> dict[str, Any]:
        query = _fold(request.query)
        terms = tuple(term for term in query.split() if term)
        currency = request.currency.upper() if request.currency else None
        candidates = self.repository.current_offers(store=request.store)
        results: list[dict[str, Any]] = []
        for row in candidates:
            if currency and str(row.get("currency", "")).upper() != currency:
                continue
            searchable = _fold(" ".join((
                str(row.get("brand") or ""),
                str(row.get("canonical_name") or ""),
                str(row.get("concentration") or ""),
                f"{row.get('size_ml') or ''} ml",
            )))
            if terms and not all(term in searchable for term in terms):
                continue
            results.append({
                "product_id": row["product_id"],
                "brand": row["brand"],
                "name": row["canonical_name"],
                "variant": {
                    "concentration": row.get("concentration"),
                    "size_ml": row.get("size_ml"),
                    "pack_count": row.get("pack_count", 1),
                },
                "offer": {
                    "offer_id": row["offer_id"],
                    "store": row["store"],
                    "url": row["product_url"],
                    "price_minor": row["price_minor"],
                    "currency": row["currency"],
                    "availability": row["availability"],
                    "last_seen_at": row["last_seen_at"],
                },
            })
        # Never compare nominal prices across currencies. Stable ordering is
        # price, then store, then URL after an optional currency filter.
        results.sort(key=lambda item: (
            item["offer"]["currency"], item["offer"]["price_minor"],
            item["offer"]["store"], item["offer"]["url"],
        ))
        return {"engine": "next", "query": request.query,
                "count": min(len(results), request.limit),
                "total_matches": len(results), "results": results[:request.limit]}

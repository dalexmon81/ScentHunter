"""Optional Meilisearch adapter for typo-tolerant catalog lookup.

PostgreSQL FTS remains the source-of-truth fallback. Meilisearch is enabled only
when MEILISEARCH_URL is configured and is populated by the explicit reindex job.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

INDEX_UID = "scenthunter_products"


class MeiliSearchUnavailable(RuntimeError):
    pass


def _settings():
    return {
        "searchableAttributes": [
            "brand", "fragrance", "concentration", "format",
            "family", "olfactory_notes", "gender",
        ],
        "filterableAttributes": [
            "brand_slug", "concentration", "format", "family", "gender",
            "availability", "country", "currency", "store_slugs", "min_price", "store_count",
        ],
        "sortableAttributes": ["min_price", "store_count"],
    }


def _request(method: str, path: str, payload=None):
    base = os.environ.get("MEILISEARCH_URL", "").strip().rstrip("/")
    if not base:
        return None
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("MEILISEARCH_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None if payload is None else json.dumps(payload, default=str).encode("utf-8")
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=4) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise MeiliSearchUnavailable(type(exc).__name__) from exc


def configure_index():
    """Configure searchable/filterable fields; safe to call during deployment."""
    return _request("PATCH", f"/indexes/{INDEX_UID}/settings", _settings())


def search_variant_ids(query: str, *, filters: dict | None = None, limit: int = 1000) -> list[str] | None:
    """Return ordered variant IDs, or None when Meilisearch is not configured."""
    payload = {
        "q": query,
        "limit": max(1, min(int(limit), 1000)),
        "attributesToRetrieve": ["id"],
    }
    clauses = []
    for field, value in (filters or {}).items():
        if value is None or value == "":
            continue
        if field not in {"brand_slug", "family", "gender", "concentration", "format", "availability", "country", "currency", "store_slugs"}:
            continue
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
        operator = "IN" if field in {"country", "currency", "store_slugs"} else "="
        if operator == "IN":
            clauses.append(f'{field} = "{escaped}"')
        else:
            clauses.append(f'{field} = "{escaped}"')
    if clauses:
        payload["filter"] = clauses
    result = _request("POST", f"/indexes/{INDEX_UID}/search", payload)
    if result is None:
        return None
    return [str(hit["id"]) for hit in result.get("hits", []) if hit.get("id")]


def reindex_catalog(session_factory=None) -> dict:
    """Build one Meilisearch document per canonical variant from persisted data."""
    from sqlalchemy import select
    from app.db import make_session_factory
    from app.models import Brand, Fragrance, Offer, ProductVariant, Store
    from datetime import datetime, timedelta, timezone

    factory = session_factory or make_session_factory()
    try:
        with factory() as session:
            rows = session.execute(
                select(Brand, Fragrance, ProductVariant)
                .join(Fragrance, Fragrance.brand_id == Brand.id)
                .join(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
            ).all()
            now = datetime.now(timezone.utc)
            documents = []
            for brand, fragrance, variant in rows:
                offers = session.execute(
                    select(Offer, Store)
                    .join(Store, Store.id == Offer.store_id)
                    .where(
                        Offer.product_variant_id == variant.id,
                        Offer.status == "active",
                        Offer.publication_status == "published",
                        Offer.availability == "in_stock",
                        Store.status == "active",
                        Offer.captured_at >= now - timedelta(hours=48),
                    )
                ).all()
                by_currency = {}
                stores = set()
                for offer, store in offers:
                    stores.add(store.id)
                    by_currency.setdefault(offer.currency, []).append(Decimal(offer.price))
                eur_prices = by_currency.get("EUR", [])
                documents.append({
                    "id": str(variant.id),
                    "brand": brand.name,
                    "brand_slug": brand.slug,
                    "fragrance": fragrance.name,
                    "fragrance_slug": fragrance.slug,
                    "concentration": variant.concentration or "",
                    "format": [
                        key for key, value in {
                            "tester": variant.is_tester,
                            "refill": variant.is_refill,
                            "gift_set": variant.is_gift_set,
                            "mini": variant.is_mini,
                        }.items() if value
                    ],
                    "family": fragrance.family or "",
                    "olfactory_notes": fragrance.olfactory_notes or [],
                    "gender": fragrance.gender or "",
                    "availability": "in_stock" if offers else "unavailable",
                    "min_price": float(min(eur_prices)) if eur_prices else 0,
                    "min_price_by_currency": {
                        currency: float(min(prices)) for currency, prices in by_currency.items()
                    },
                    "store_count": len(stores),
                    "store_slugs": sorted({store.slug for _, store in offers}),
                    "country": sorted({store.country for _, store in offers if store.country}),
                    "currency": sorted(by_currency),
                })
            if documents:
                _request("POST", f"/indexes/{INDEX_UID}/documents", documents)
            return {"indexed": len(documents), "index": INDEX_UID}
    finally:
        if session_factory is None:
            factory.kw["bind"].dispose()

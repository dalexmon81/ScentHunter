"""Authenticated, read-only PostgreSQL Phase 0 baseline export."""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, IngestionRaw, IngestionRun, Offer, ProductVariant, Store

router = APIRouter()

# The Phase 0 scope is intentionally fixed. Store aliases map the agreed
# retailer names to the canonical slugs used by the PostgreSQL catalog.
STORE_SCOPE = (
    ("bplatz", "bplatz"),
    ("deloox", "deloox-be"),
    ("easycosmetic", "easycosmetic-de"),
    ("notino", "notino-fr"),
    ("orioudh", "orioudh"),
    ("parfumcity", "parfumcity"),
    ("parfumzentrum", "parfumzentrum-de"),
    ("perfumemarket", "perfumemarket"),
    ("sabina", "sabina-es"),
)


def _authorize(authorization: str) -> None:
    expected = str(os.environ.get("SCENTHUNTER_BASELINE_TOKEN") or "")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _iso(value):
    return value.isoformat() if value is not None else None


@router.get("/admin/phase0/postgres-baseline")
def postgres_phase0_baseline(authorization: str = Header(default="")):
    """Return a point-in-time catalog/retailer snapshot without writing anything."""
    _authorize(authorization)

    from app.api.catalog_search import _eligible_offer_rows, _engine

    now = datetime.now(timezone.utc)
    with Session(_engine()) as session:
        # Enforce read-only at the PostgreSQL transaction level, not merely by convention.
        session.execute(text("SET TRANSACTION READ ONLY"))
        catalog_counts = {
            "brands": session.scalar(select(func.count()).select_from(Brand)) or 0,
            "fragrances": session.scalar(select(func.count()).select_from(Fragrance)) or 0,
            "variants": session.scalar(select(func.count()).select_from(ProductVariant)) or 0,
        }

        stores = session.scalars(select(Store)).all()
        stores_by_slug = {store.slug: store for store in stores}
        eligible_rows = _eligible_offer_rows(session, now)
        publishable_ids = {offer.id for offer, _store, _raw in eligible_rows}

        statement = (
            select(Offer, Store, IngestionRaw, ProductVariant, Fragrance, Brand)
            .join(Store, Offer.store_id == Store.id)
            .outerjoin(IngestionRaw, Offer.ingestion_raw_id == IngestionRaw.id)
            .outerjoin(ProductVariant, Offer.product_variant_id == ProductVariant.id)
            .outerjoin(Fragrance, ProductVariant.fragrance_id == Fragrance.id)
            .outerjoin(Brand, Fragrance.brand_id == Brand.id)
            .order_by(Store.slug, Offer.captured_at.desc(), Offer.id)
        )
        rows = session.execute(statement).all()

        raw_counts: dict[str, dict[str, int]] = {}
        for store_id, status, count in session.execute(
            select(IngestionRaw.store_id, IngestionRaw.status, func.count())
            .group_by(IngestionRaw.store_id, IngestionRaw.status)
        ).all():
            raw_counts.setdefault(str(store_id), {})[str(status)] = int(count)

        run_counts: dict[str, dict[str, int]] = {}
        latest_run_by_store: dict[str, str] = {}
        for store_id, status, count, discovered, created, updated, rejected, latest in session.execute(
            select(
                IngestionRun.store_id,
                IngestionRun.status,
                func.count(),
                func.coalesce(func.sum(IngestionRun.products_discovered), 0),
                func.coalesce(func.sum(IngestionRun.offers_created), 0),
                func.coalesce(func.sum(IngestionRun.offers_updated), 0),
                func.coalesce(func.sum(IngestionRun.offers_rejected), 0),
                func.max(IngestionRun.started_at),
            ).group_by(IngestionRun.store_id, IngestionRun.status)
        ).all():
            key = str(store_id)
            run_counts.setdefault(key, {})[str(status)] = {
                "runs": int(count),
                "products_discovered": int(discovered),
                "offers_created": int(created),
                "offers_updated": int(updated),
                "offers_rejected": int(rejected),
            }
            if latest is not None:
                previous = latest_run_by_store.get(key)
                if previous is None or _iso(latest) > previous:
                    latest_run_by_store[key] = _iso(latest)

        offers_by_slug: dict[str, list[dict]] = {}
        for offer, store, raw, variant, fragrance, brand in rows:
            offers_by_slug.setdefault(store.slug, []).append({
                "canonical_product_id": str(fragrance.id) if fragrance else None,
                "brand": brand.name if brand else None,
                "fragrance": fragrance.name if fragrance else None,
                "concentration": variant.concentration if variant else None,
                "size_ml": variant.size_ml if variant else None,
                "variant_type": (
                    "tester" if variant and variant.is_tester else
                    "refill" if variant and variant.is_refill else
                    "gift_set" if variant and variant.is_gift_set else
                    "mini" if variant and variant.is_mini else "standard"
                ) if variant else None,
                "gtin": variant.gtin if variant else None,
                "external_product_id": offer.external_product_id,
                "offer_url": offer.url,
                "price": str(offer.price),
                "currency": offer.currency,
                "availability": offer.availability,
                "captured_at": _iso(offer.captured_at),
                "source": offer.source,
                "offer_status": offer.status,
                "ingestion_status": raw.status if raw else "missing_raw_record",
                "match_method": raw.match_method if raw else None,
                "match_confidence": str(raw.match_confidence) if raw and raw.match_confidence is not None else None,
                "is_valid_offer": offer.id in publishable_ids,
            })

        store_report = []
        for scope_name, db_slug in STORE_SCOPE:
            store = stores_by_slug.get(db_slug)
            offers = offers_by_slug.get(db_slug, [])
            store_report.append({
                "store": scope_name,
                "database_slug": db_slug,
                "database_present": store is not None,
                "status": store.status if store else "missing",
                "domain": store.domain if store else None,
                "last_successful_sync_at": _iso(store.last_successful_sync_at) if store else None,
                "consecutive_failures": store.consecutive_failures if store else None,
                "raw_ingestion_by_status": raw_counts.get(str(store.id), {}) if store else {},
                "ingestion_runs_by_status": run_counts.get(str(store.id), {}) if store else {},
                "last_ingestion_run_at": latest_run_by_store.get(str(store.id)) if store else None,
                "total_offers": len(offers),
                "active_offers": sum(row["offer_status"] == "active" for row in offers),
                "publishable_offers": sum(row["is_valid_offer"] for row in offers),
                "offers": offers,
            })

        queue_rows = session.execute(text(
            "SELECT stage, status, COUNT(*) FROM ingestion_queue_jobs GROUP BY stage, status ORDER BY stage, status"
        )).all()
        queue = [
            {"stage": stage, "status": status, "count": int(count)}
            for stage, status, count in queue_rows
        ]

        return {
            "report": "phase0-postgresql-read-only",
            "generated_at": now.isoformat(),
            "database_backend": "postgresql",
            "read_only": True,
            "scope": [name for name, _slug in STORE_SCOPE],
            "catalog": catalog_counts,
            "queue": queue,
            "stores": store_report,
            "totals": {
                "stores_in_scope": len(STORE_SCOPE),
                "stores_present": sum(row["database_present"] for row in store_report),
                "active_stores": sum(row["status"] == "active" for row in store_report),
                "offers": sum(row["total_offers"] for row in store_report),
                "active_offers": sum(row["active_offers"] for row in store_report),
                "publishable_offers": sum(row["publishable_offers"] for row in store_report),
            },
        }

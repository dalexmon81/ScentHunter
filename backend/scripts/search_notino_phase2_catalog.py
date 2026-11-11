"""Read-only catalog-first search for the isolated Notino Phase 2 staging DB.

This is an operator/test entry point, not a public API. It never performs
network requests or retailer scraping and refuses databases outside /data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, select, and_, or_
from sqlalchemy.orm import Session, joinedload

from app.models import Offer, ProductVariant, Fragrance, Brand, Store


DEFAULT_DB = Path("/data/notino-phase2/catalog.sqlite3")


def search(session: Session, query: str, limit: int = 20) -> list[dict]:
    term = (query or "").strip()
    if not term:
        raise ValueError("query must not be empty")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    stmt = (
        select(Offer)
        .join(Offer.product_variant)
        .join(ProductVariant.fragrance)
        .join(Fragrance.brand)
        .join(Offer.store)
        .options(
            joinedload(Offer.product_variant)
            .joinedload(ProductVariant.fragrance)
            .joinedload(Fragrance.brand),
            joinedload(Offer.store),
        )
        .where(
            and_(
                Offer.status == "active",
                Offer.price > 0,
                Offer.currency == "EUR",
                Offer.availability == "in_stock",
                Offer.url.like("http%"),
                Store.slug == "notino-fr",
                or_(
                    Brand.name.ilike(f"%{term}%"),
                    Fragrance.name.ilike(f"%{term}%"),
                    ProductVariant.canonical_key.ilike(f"%{term}%"),
                ),
            )
        )
        .order_by(Offer.price.asc(), Offer.captured_at.desc())
        .limit(limit)
    )

    rows = session.scalars(stmt).unique().all()
    results = []
    for offer in rows:
        variant = offer.product_variant
        fragrance = variant.fragrance
        results.append({
            "brand": fragrance.brand.name,
            "fragrance": fragrance.name,
            "concentration": variant.concentration,
            "size_ml": variant.size_ml,
            "is_tester": variant.is_tester,
            "is_refill": variant.is_refill,
            "is_gift_set": variant.is_gift_set,
            "price": str(offer.price),
            "currency": offer.currency,
            "availability": offer.availability,
            "store": offer.store.name,
            "url": offer.url,
            "captured_at": offer.captured_at.isoformat(),
            "external_product_id": offer.external_product_id,
        })
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Brand or fragrance name")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    db_path = args.database.resolve()
    if Path("/data") not in db_path.parents:
        raise SystemExit("STOP: read-only Phase 2 search is restricted to /data")
    if not db_path.is_file():
        raise SystemExit(f"STOP: Phase 2 database does not exist: {db_path}")

    # SQLite URI mode=ro prevents accidental writes by this search utility.
    engine = create_engine(
        f"sqlite:///file:{db_path}?mode=ro&uri=true",
        connect_args={"check_same_thread": False},
    )
    try:
        with Session(engine) as session:
            rows = search(session, args.query, args.limit)
        print(json.dumps({
            "query": args.query,
            "count": len(rows),
            "source": "notino_phase2_catalog_sqlite",
            "live_scraping": False,
            "offers": rows,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

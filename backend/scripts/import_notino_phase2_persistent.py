"""Import the authorized Notino CJ snapshot into an explicitly isolated persistent Phase 2 SQLite DB.

This command refuses paths outside /data and requires --apply. It never uses the
legacy catalog DB path or production credentials. Exact GTIN matches only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.db import make_engine
from app.models import Base, IngestionRaw, Offer, PriceHistory, Store
from app.services.notino_phase2_adapter import persist_notino_record
from scripts.build_notino_match_candidates import iter_perfume_rows


def money(value: str):
    import re
    match = re.search(r"([0-9][0-9.,]*)\s*([A-Z]{3})", (value or "").strip(), re.I)
    if not match:
        return None, None
    number, currency = match.groups()
    if "," in number and "." in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(",", ".")
    try:
        return Decimal(number), currency.upper()
    except InvalidOperation:
        return None, currency.upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("--database", type=Path, default=Path("/data/notino-phase2/catalog.sqlite3"))
    parser.add_argument("--catalog", type=Path, default=BACKEND / "product_catalog.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.apply:
        raise SystemExit("STOP: persistent writes require explicit --apply")
    if not args.feed.is_file() or args.feed.stat().st_size == 0:
        raise SystemExit("STOP: feed missing or empty")
    db_path = args.database.resolve()
    if Path("/data") not in db_path.parents:
        raise SystemExit("STOP: persistent Phase 2 database must be below /data")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["SCENTHUNTER_CATALOG_DATABASE_URL"] = f"sqlite:///{db_path}"

    rows = list(iter_perfume_rows(args.feed))
    ids = [str(row.get("id") or "").strip() for row in rows]
    if not rows or any(not x for x in ids) or len(ids) != len(set(ids)):
        raise SystemExit("STOP: feed has empty or duplicate retailer product IDs")

    # Idempotently seed canonical identities into this isolated database.
    engine = make_engine()
    try:
        Base.metadata.create_all(engine)
        subprocess.run(
            [sys.executable, str(BACKEND / "scripts" / "seed_catalog.py"),
             "--catalog", str(args.catalog), "--apply"],
            check=True, cwd=ROOT, env=os.environ.copy(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        counts, reasons = Counter(), Counter()
        observed_at = datetime.now(timezone.utc).isoformat()
        with Session(engine) as session, session.begin():
            store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
            if store is None:
                store = Store(id=uuid4(), name="NOTINO.fr", slug="notino-fr",
                              domain="notino.fr", country="FR", currency="EUR", status="active")
                session.add(store)
                session.flush()
            store_id = store.id
            # Read the existing retailer IDs once. Per-row SELECTs made repeat
            # imports perform ~19,000 SQLite round trips for a 9.5k-row feed.
            existing_offer_ids = set(session.scalars(
                select(Offer.external_product_id).where(
                    Offer.store_id == store_id,
                    Offer.external_product_id.is_not(None),
                )
            ).all())
            existing_raw_ids = set(session.scalars(
                select(IngestionRaw.external_product_id).where(
                    IngestionRaw.store_id == store_id,
                    IngestionRaw.external_product_id.is_not(None),
                )
            ).all())
            for row in rows:
                external_id = str(row.get("id") or "").strip()
                # Do not re-stage thousands of unchanged unmatched feed rows.
                # Existing published offers are re-observed to refresh price/stock.
                if external_id in existing_raw_ids and external_id not in existing_offer_ids:
                    counts["unchanged_unmatched_skipped"] += 1
                    continue

                price, price_currency = money(row.get("price", ""))
                sale_price, sale_currency = money(row.get("sale_price", ""))
                if sale_price is not None and sale_price <= 0:
                    sale_price = None
                record = {
                    "external_id": external_id,
                    "gtin": str(row.get("gtin") or "").strip(),
                    "price": str(price) if price is not None else None,
                    "sale_price": str(sale_price) if sale_price is not None else None,
                    "currency": sale_currency or price_currency or "EUR",
                    "availability": str(row.get("availability") or "").strip().casefold(),
                    "affiliate_url": str(row.get("link") or "").strip(),
                    "captured_at": observed_at,
                    "source_last_updated": str(row.get("last_updated") or "").strip() or None,
                    "title": str(row.get("title") or "").strip(),
                }
                result = persist_notino_record(session, store_id=store_id, raw_record=record)
                counts[result.status] += 1
                if result.reason:
                    reasons[result.reason] += 1

            offers = session.scalar(select(func.count()).select_from(Offer).where(Offer.store_id == store_id)) or 0
            history = session.scalar(select(func.count()).select_from(PriceHistory).join(Offer).where(Offer.store_id == store_id)) or 0
            raw_count = session.scalar(select(func.count()).select_from(IngestionRaw).where(IngestionRaw.store_id == store_id)) or 0
            duplicates = session.execute(
                select(Offer.external_product_id, func.count())
                .where(Offer.store_id == store_id, Offer.external_product_id.is_not(None))
                .group_by(Offer.external_product_id).having(func.count() > 1)
            ).all()
            result = {
                "status": "passed" if offers > 0 and history >= offers and not duplicates else "failed",
                "feed_rows": len(rows), "adapter_results": dict(counts),
                "hold_reasons": dict(reasons), "persistent_offers": offers,
                "price_history_rows": history, "raw_rows_persisted": raw_count,
                "duplicate_offer_external_ids": len(duplicates),
                "database_path": str(db_path), "database_scope": "dedicated isolated staging volume",
                "production_database_touched": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "passed" else 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

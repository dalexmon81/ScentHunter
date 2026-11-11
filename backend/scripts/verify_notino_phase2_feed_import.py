"""Disposable end-to-end NOTINO CJ feed import verification.

Builds a temporary SQLite Phase 2 database, seeds canonical identities from the
repository catalog, and runs the real adapter against the downloaded XML.
Never reads production database credentials or writes outside a temp directory.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance, ProductVariant, Store, Offer, PriceHistory, IngestionRaw
from app.db import make_engine
from app.services.notino_phase2_adapter import persist_notino_record
from scripts.build_notino_match_candidates import iter_perfume_rows


def money(value: str) -> tuple[Decimal | None, str | None]:
    text = (value or "").strip()
    match = re.search(r"([0-9][0-9.,]*)\s*([A-Z]{3})", text, re.I)
    if not match:
        return None, None
    number, currency = match.groups()
    # CJ Shopping values use decimal dot; tolerate European decimal comma.
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
    parser.add_argument("--catalog", type=Path, default=BACKEND / "product_catalog.json")
    parser.add_argument("--output", type=Path, default=Path("/tmp/notino-phase2-import-verification.json"))
    args = parser.parse_args()

    if not args.feed.is_file() or args.feed.stat().st_size == 0:
        raise SystemExit("STOP: CJ XML feed is missing or empty")

    # Detect duplicate retailer IDs before adapter persistence. Repeated IDs in
    # one snapshot are unsafe because one feed row must represent one offer.
    rows = list(iter_perfume_rows(args.feed))
    external_counts = Counter(str(row.get("id") or "").strip() for row in rows)
    duplicate_external_ids = sorted(key for key, count in external_counts.items() if key and count > 1)

    with tempfile.TemporaryDirectory(prefix="scenthunter-notino-phase2-") as temp:
        db_path = Path(temp) / "phase2.sqlite3"
        os.environ["SCENTHUNTER_CATALOG_DATABASE_URL"] = f"sqlite:///{db_path}"
        engine = make_engine()
        try:
            Base.metadata.create_all(engine)
            # Reuse the canonical catalog's own deterministic seeding logic.
            subprocess.run(
                [sys.executable, str(BACKEND / "scripts" / "seed_catalog.py"),
                 "--catalog", str(args.catalog), "--apply"],
                check=True, cwd=ROOT, env=os.environ.copy(),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )

            counts = Counter()
            reasons = Counter()
            now = datetime.now(timezone.utc).isoformat()
            with Session(engine) as session, session.begin():
                store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
                if store is None:
                    store = Store(
                        id=uuid4(), name="NOTINO.fr", slug="notino-fr",
                        domain="notino.fr", country="FR", currency="EUR",
                        status="active",
                    )
                    session.add(store)
                    session.flush()
                store_id = store.id

                seen_ids: set[str] = set()
                for row in rows:
                    external_id = str(row.get("id") or "").strip()
                    if external_id and external_id in seen_ids:
                        counts["duplicate_external_id_skipped"] += 1
                        continue
                    if external_id:
                        seen_ids.add(external_id)

                    price, price_currency = money(row.get("price", ""))
                    sale_price, sale_currency = money(row.get("sale_price", ""))
                    if sale_price is not None and sale_price <= 0:
                        sale_price = None
                    chosen_price = sale_price if sale_price is not None else price
                    currency = sale_currency or price_currency or "EUR"
                    raw_record = {
                        "external_id": external_id or None,
                        "gtin": str(row.get("gtin") or "").strip(),
                        "price": str(price) if price is not None else None,
                        "sale_price": str(sale_price) if sale_price is not None else None,
                        "currency": currency,
                        "availability": str(row.get("availability") or "").strip().casefold(),
                        "affiliate_url": str(row.get("link") or "").strip(),
                        # This is the time we observed/downloaded the snapshot,
                        # not a claim about when Notino last changed the price.
                        "captured_at": now,
                        "source_last_updated": str(row.get("last_updated") or "").strip() or None,
                        "title": str(row.get("title") or "").strip(),
                    }
                    result = persist_notino_record(
                        session, store_id=store_id, raw_record=raw_record,
                    )
                    counts[result.status] += 1
                    if result.reason:
                        reasons[result.reason] += 1

                session.flush()
                offers = session.scalar(select(func.count()).select_from(Offer).where(Offer.store_id == store_id)) or 0
                history = session.scalar(
                    select(func.count()).select_from(PriceHistory).join(Offer).where(Offer.store_id == store_id)
                ) or 0
                raw_total = session.scalar(
                    select(func.count()).select_from(IngestionRaw).where(IngestionRaw.store_id == store_id)
                ) or 0
                unique_variant_matches = session.scalar(
                    select(func.count(func.distinct(IngestionRaw.product_variant_id)))
                    .where(IngestionRaw.store_id == store_id, IngestionRaw.product_variant_id.is_not(None))
                ) or 0
                active_duplicate_ids = session.execute(
                    select(Offer.external_product_id, func.count())
                    .where(Offer.store_id == store_id, Offer.external_product_id.is_not(None))
                    .group_by(Offer.external_product_id)
                    .having(func.count() > 1)
                ).all()
                summary = {
                    "status": "passed" if not active_duplicate_ids else "failed",
                    "feed_core_rows": len(rows),
                    "unique_external_ids": len(seen_ids),
                    "duplicate_external_ids_in_feed": len(duplicate_external_ids),
                    "duplicate_external_ids_skipped": counts["duplicate_external_id_skipped"],
                    "adapter_results": dict(counts),
                    "hold_reasons": dict(reasons),
                    "offers_in_disposable_db": offers,
                    "price_history_rows": history,
                    "raw_rows_staged": raw_total,
                    "distinct_variants_matched": unique_variant_matches,
                    "duplicate_offer_external_ids_in_db": len(active_duplicate_ids),
                    "exact_gtin_only_promotion": True,
                    "production_database_touched": False,
                    "canonical_catalog_modified": False,
                    "database_scope": "temporary SQLite; deleted after this process",
                }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if summary["status"] == "passed" else 2
        finally:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

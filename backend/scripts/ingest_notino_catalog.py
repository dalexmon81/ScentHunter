"""Explicit, bounded Notino CJ feed ingestion into the isolated Phase 2 catalog.

Dry-run is the default. Database writes require both --apply and
--confirm-notino-import. This command is never called by user-facing search.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from app.db import make_engine
from app.models import Store
from app.services.connector_ingestion import persist_connector_record
from scenthunter_next_engine.next_engine_service import NextEngineService
from scenthunter_next_engine.offer_normalizer import normalize_offer


EXPECTED_REVISION = "0005_connector_quarantine"
NOTINO_STORE_SLUG = "notino-fr"
NOTINO_STORE_DOMAIN = "notino.fr"


def _ensure_notino_store(engine):
    inspector = inspect(engine)
    required = {"stores", "alembic_version", "ingestion_raw", "offers"}
    if not required.issubset(set(inspector.get_table_names())):
        raise RuntimeError("phase2_catalog_schema_missing; run the reviewed Alembic migration first")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f"phase2_schema_revision_mismatch:{revision!r}")
    with Session(engine) as session, session.begin():
        store = session.scalar(select(Store).where(Store.slug == NOTINO_STORE_SLUG))
        if store is None:
            store = Store(
                name="Notino.fr", slug=NOTINO_STORE_SLUG, domain=NOTINO_STORE_DOMAIN,
                country="FR", currency="EUR", status="active",
            )
            session.add(store)
            session.flush()
        elif store.status != "active" or store.domain not in {NOTINO_STORE_DOMAIN, "www.notino.fr"}:
            raise RuntimeError("existing_notino_store_is_not_active_or_has_unexpected_domain")
        return store.id


async def run_ingestion(*, connector, matcher, engine=None, apply=False, max_products=1000):
    counts = {
        "discovered": 0, "matched": 0, "unmatched": 0,
        "rejected": 0, "promoted": 0,
    }
    store_id = None
    cursor = None
    while counts["discovered"] < max_products:
        page_limit = min(1000, max_products - counts["discovered"])
        page = await connector.discover_products(cursor=cursor, limit=page_limit)
        if not page:
            break
        if apply and store_id is None:
            store_id = _ensure_notino_store(engine)
        for product in page:
            raw = dict(product.raw_payload)
            counts["discovered"] += 1
            if apply:
                with Session(engine) as session, session.begin():
                    result = persist_connector_record(
                        session, connector=connector, store_id=store_id,
                        raw_record=raw, matcher=matcher,
                    )
                if result.status == "promoted":
                    counts["promoted"] += 1
                    counts["matched"] += 1
                elif result.status == "matched":
                    counts["matched"] += 1
                    counts["rejected"] += 1
                else:
                    counts["unmatched"] += 1
                continue

            try:
                parsed = connector.parse_raw(raw)
                validation = connector.validate_offer(parsed)
                normalized = normalize_offer(parsed, retailer=connector.store_key)
            except (TypeError, ValueError):
                counts["rejected"] += 1
                continue
            if parsed.get("currency_explicit") is not True or not validation.valid:
                counts["rejected"] += 1
                continue
            aggregation = matcher.process_offers([normalized])
            if aggregation.matched_offer_count == 1 and len(aggregation.groups) == 1:
                counts["matched"] += 1
            else:
                counts["unmatched"] += 1

        if len(page) < page_limit:
            break
        cursor = str(int(cursor or "0") + len(page))

    counts["truncated"] = bool(
        counts["discovered"] >= max_products
        and await connector.discover_products(cursor=cursor or str(counts["discovered"]), limit=1)
    )
    counts["mode"] = "apply" if apply else "dry_run"
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist staged and validated Notino offers")
    parser.add_argument(
        "--confirm-notino-import", action="store_true",
        help="required together with --apply to authorize Phase 2 database writes",
    )
    parser.add_argument("--max-products", type=int, default=1000)
    args = parser.parse_args()
    if args.max_products < 1:
        parser.error("--max-products must be positive")
    if args.apply and not args.confirm_notino_import:
        parser.error("--apply also requires --confirm-notino-import")

    connector = NotinoAffiliateFeedConnector()
    matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
    engine = None
    try:
        if args.apply:
            engine = make_engine()
        result = asyncio.run(run_ingestion(
            connector=connector, matcher=matcher, engine=engine,
            apply=args.apply, max_products=args.max_products,
        ))
        print(json.dumps({"status": "completed", **result}, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "error": f"{type(exc).__name__}:{exc}",
            "database_written": bool(args.apply),
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

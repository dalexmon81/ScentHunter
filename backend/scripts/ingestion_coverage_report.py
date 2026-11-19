"""Read-only operational coverage report for canonical retailer ingestion.

This command reads ingestion_runs and staged raw rows only. It never downloads
retailer data, starts jobs, changes offers, or relaxes publication validation.
Run it inside the pilot container:

    python scripts/ingestion_coverage_report.py --hours 168

The report separates discovery volume, promoted offer volume, unresolved rows,
and the latest per-store run. A store with zero runs is visibly different from
a store that ran but produced no safe matches.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import IngestionRaw, IngestionRun, Offer, Store


def build_report(session: Session, *, since: datetime) -> dict:
    stores = session.scalars(select(Store).order_by(Store.slug)).all()
    rows = []
    for store in stores:
        runs = session.scalars(
            select(IngestionRun)
            .where(IngestionRun.store_id == store.id, IngestionRun.started_at >= since)
            .order_by(IngestionRun.started_at.desc())
        ).all()
        run_totals = {
            "runs": len(runs),
            "completed": sum(run.status == "completed" for run in runs),
            "partial": sum(run.status == "partial" for run in runs),
            "failed": sum(run.status == "failed" for run in runs),
            "products_discovered": sum(run.products_discovered or 0 for run in runs),
            "offers_created": sum(run.offers_created or 0 for run in runs),
            "offers_updated": sum(run.offers_updated or 0 for run in runs),
            "offers_rejected": sum(run.offers_rejected or 0 for run in runs),
        }
        latest = runs[0] if runs else None

        raw_rows = session.execute(
            select(IngestionRaw.status, IngestionRaw.rejection_reason, func.count())
            .where(IngestionRaw.store_id == store.id, IngestionRaw.created_at >= since)
            .group_by(IngestionRaw.status, IngestionRaw.rejection_reason)
        ).all()
        raw_counts = Counter()
        reason_counts = Counter()
        for status, reason, count in raw_rows:
            raw_counts[str(status)] += int(count)
            if reason:
                reason_counts[str(reason)[:120]] += int(count)

        active_offers = session.scalar(
            select(func.count()).select_from(Offer).where(
                Offer.store_id == store.id, Offer.status == "active"
            )
        ) or 0

        rows.append({
            "store": store.slug,
            "name": store.name,
            "connector_status": store.status,
            "last_successful_sync_at": (
                store.last_successful_sync_at.isoformat()
                if store.last_successful_sync_at else None
            ),
            "consecutive_failures": store.consecutive_failures,
            "latest_run": ({
                "id": str(latest.id),
                "status": latest.status,
                "started_at": latest.started_at.isoformat() if latest.started_at else None,
                "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
                "errors": list(latest.errors or [])[-5:],
            } if latest else None),
            **run_totals,
            "staged_rows_by_status": dict(sorted(raw_counts.items())),
            "top_unresolved_reasons": [
                {"reason": reason, "count": count}
                for reason, count in reason_counts.most_common(10)
            ],
            "active_offers_in_database": int(active_offers),
        })

    since_text = since.astimezone(timezone.utc).isoformat()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": since_text,
        "stores": rows,
        "totals": {
            "stores": len(rows),
            "stores_with_runs": sum(row["runs"] > 0 for row in rows),
            "products_discovered": sum(row["products_discovered"] for row in rows),
            "offers_created": sum(row["offers_created"] for row in rows),
            "offers_updated": sum(row["offers_updated"] for row in rows),
            "offers_rejected": sum(row["offers_rejected"] for row in rows),
            "active_offers_in_database": sum(row["active_offers_in_database"] for row in rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=168)
    args = parser.parse_args()
    if isinstance(args.hours, bool) or not 1 <= args.hours <= 24 * 365:
        parser.error("--hours must be between 1 and 8760")
    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    engine = make_engine()
    try:
        with Session(engine) as session:
            report = build_report(session, since=since)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

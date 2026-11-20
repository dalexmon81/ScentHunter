"""Queue the first authorized Notino feed discovery run.

This is an explicit operator command. It does not download the feed itself;
the registered Celery worker performs all connector I/O in the background.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import make_engine
from app.models import Store
from app.workers.queueing import QueueNotConfigured, enqueue_discovery


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")

    engine = make_engine()
    try:
        with Session(engine) as session:
            store = session.scalar(
                select(Store).where(Store.slug == "notino-fr", Store.status == "active")
            )
            if store is None:
                raise SystemExit(
                    "Active notino-fr store is missing; seed it explicitly before queueing."
                )
            store_id = store.id

        try:
            result = enqueue_discovery(store_id, limit=args.limit)
        except QueueNotConfigured as exc:
            raise SystemExit(str(exc)) from None

        print(json.dumps({
            "status": "queued",
            "store": "notino-fr",
            "store_id": str(store_id),
            "task_id": result.id,
            "limit": args.limit,
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

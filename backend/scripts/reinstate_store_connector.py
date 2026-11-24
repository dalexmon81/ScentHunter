"""Explicitly reinstate a quarantined store connector after operator review."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import make_session_factory
from app.models import Store
from app.monitoring.connector_health import reinstate_connector


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-slug", required=True)
    parser.add_argument(
        "--confirm", action="store_true",
        help="Confirm the connector was manually checked before reinstatement",
    )
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required; reinstatement is never automatic")

    session_factory = make_session_factory()
    try:
        with session_factory() as session, session.begin():
            store = session.query(Store).filter_by(slug=args.store_slug).one_or_none()
            if store is None:
                print(f"Unknown store: {args.store_slug}", file=sys.stderr)
                return 2
            changed = reinstate_connector(
                session, store_id=store.id, confirmed=True
            )
            if not changed:
                print(f"Store {args.store_slug} is not quarantined; no change made")
                return 0
        print(f"Store {args.store_slug} reinstated. Check connector logs before resuming ingestion.")
        return 0
    finally:
        session_factory.kw["bind"].dispose()


if __name__ == "__main__":
    raise SystemExit(main())

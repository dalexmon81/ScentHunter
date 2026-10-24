"""Read-only-by-default audit and opt-in retirement of invalid Deloox catalog URLs.

Run an audit:
    python -m backend.scenthunter_next_engine.catalog_url_hygiene

Apply the narrowly scoped repair only after reviewing the JSON report:
    python -m backend.scenthunter_next_engine.catalog_url_hygiene --apply

This retires rows that no longer satisfy the same Deloox product-URL admission
contract used by discovery. It never deletes historical product data or edits
product identities.
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Iterable

from backend import catalog_engine


def classify_invalid_urls(rows: Iterable[dict]) -> list[dict]:
    """Return active Deloox URL rows rejected by the current admission contract."""
    invalid = []
    base_url = catalog_engine.STORES["deloox"]
    for row in rows:
        if not row.get("active"):
            continue
        if catalog_engine._html_product_url("deloox", row.get("url"), base_url) is None:
            invalid.append({
                "store": row.get("store", "deloox"),
                "url": row.get("url"),
                "slug": row.get("slug"),
                "reason": "rejected_by_current_product_url_admission",
            })
    return invalid


def audit_or_retire(apply: bool = False) -> dict:
    """Audit invalid active Deloox URLs; optionally deactivate them transactionally."""
    conn = catalog_engine.db()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT store,url,slug,active FROM store_urls WHERE store='deloox' AND active=1"
            ).fetchall()
        ]
        invalid = classify_invalid_urls(rows)
        retired = 0
        if apply and invalid:
            now = time.time()
            with conn:
                for item in invalid:
                    result = conn.execute(
                        """UPDATE store_urls SET active=0
                           WHERE store='deloox' AND url=? AND active=1""",
                        (item["url"],),
                    )
                    retired += max(0, result.rowcount)
        return {
            "read_only": not apply,
            "database_mutated": bool(apply and retired),
            "mode": "apply" if apply else "audit",
            "active_deloox_urls_examined": len(rows),
            "invalid_active_urls_found": len(invalid),
            "rows_retired": retired,
            "invalid_urls": invalid,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="deactivate invalid active Deloox URL rows; default is read-only",
    )
    args = parser.parse_args()
    print(json.dumps(audit_or_retire(apply=args.apply), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

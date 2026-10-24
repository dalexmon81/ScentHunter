"""Read-only audit of invalid active Deloox catalog URLs.

Run with:
    python -m backend.scenthunter_next_engine.catalog_url_hygiene

This command reports URLs rejected by the catalog's current product-URL
admission contract. It never writes to the database or changes product data.
"""
from __future__ import annotations

import json
from typing import Iterable

from backend import catalog_engine


def classify_invalid_urls(rows: Iterable[dict]) -> list[dict]:
    """Return active Deloox URL rows rejected by the current admission contract."""
    invalid = []
    base_url = catalog_engine.STORES["deloox"][0]
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


def audit() -> dict:
    """Inspect active Deloox URL rows without mutating the catalog."""
    conn = catalog_engine.db()
    try:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT store,url,slug,active FROM store_urls WHERE store='deloox' AND active=1"
            ).fetchall()
        ]
        invalid = classify_invalid_urls(rows)
        return {
            "read_only": True,
            "database_mutated": False,
            "active_deloox_urls_examined": len(rows),
            "invalid_active_urls_found": len(invalid),
            "invalid_urls": invalid,
        }
    finally:
        conn.close()


def main() -> int:
    print(json.dumps(audit(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

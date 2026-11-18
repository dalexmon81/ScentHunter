#!/usr/bin/env python3
"""Read-only live smoke test for the Notino public storefront fallback.

This script deliberately bypasses the CJ feed and never writes to any database.
It prints structured diagnostics for a small fixed set of real product queries.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from scrapers.notino import scraper


QUERIES = (
    "French Avenue Liquid Brun Eau de Parfum",
    "Dior Sauvage Eau de Parfum",
    "Bleu de Chanel Eau de Parfum",
    "Yves Saint Laurent Y Eau de Parfum",
    "Acqua di Gio Profondo Eau de Parfum",
)


def compact_offer(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row.get("name"),
        "brand": row.get("brand"),
        "price": row.get("price"),
        "currency": row.get("currency"),
        "size_ml": row.get("size_ml"),
        "availability": row.get("availability"),
        "url": row.get("url"),
        "source": row.get("offer_source"),
    }


def main() -> int:
    reports = []
    verified_count = 0
    for query in QUERIES:
        try:
            raw_rows, diagnostics = scraper._search_public(query)
            rows = [
                offer
                for raw in raw_rows
                if isinstance(raw, dict)
                for offer in [scraper._normalise_public_offer(raw, query)]
                if offer is not None
            ]
            verified_count += bool(rows)
            reports.append({
                "query": query,
                "verified_offers": len(rows),
                "offers": [compact_offer(row) for row in rows[:2]],
                "discovery": diagnostics,
            })
        except Exception as exc:  # diagnostics must retain per-query failures
            reports.append({
                "query": query,
                "verified_offers": 0,
                "error": f"{type(exc).__name__}: {exc}",
            })

    result = {
        "mode": "read_only_public_storefront",
        "database_touched": False,
        "cj_feed_used": False,
        "queries": len(QUERIES),
        "queries_with_verified_offers": verified_count,
        "reports": reports,
    }
    print("NOTINO_PUBLIC_FALLBACK_SMOKE=" + json.dumps(result, ensure_ascii=False), flush=True)
    # A single verified product is enough to prove the path works end-to-end;
    # coverage across all five queries is reported separately.
    return 0 if verified_count else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Read-only live acceptance smoke for the direct Notino PostgreSQL connector."""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.connectors.notino_public import NotinoPublicStorefrontConnector


def compact(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {"result": "not_found"}
    return {
        "name": row.get("name"),
        "brand": row.get("brand"),
        "size_ml": row.get("size_ml") or row.get("sizeml"),
        "concentration": row.get("concentration"),
        "price": row.get("price"),
        "currency": row.get("currency"),
        "currency_explicit": row.get("currency_explicit"),
        "availability": row.get("availability"),
        "url": row.get("url"),
        "source": row.get("source"),
    }


async def run() -> int:
    connector = NotinoPublicStorefrontConnector()
    report: list[dict[str, Any]] = []
    try:
        candidates = await connector.discover_products(limit=10)
    except Exception as exc:
        result = {
            "mode": "direct_notino_public_storefront",
            "database_touched": False,
            "cj_feed_used": False,
            "discovered": 0,
            "verified": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "products": [],
        }
        print("NOTINO_DIRECT_CONNECTOR_SMOKE=" + json.dumps(result, ensure_ascii=False), flush=True)
        return 1

    verified = 0
    for candidate in candidates:
        try:
            row = await connector.fetch_product(candidate.external_product_id)
            item = compact(row)
            item["candidate_name"] = candidate.raw_payload.get("name")
            item["candidate_query"] = candidate.raw_payload.get("query")
            item["candidate_url"] = candidate.product_url
            valid = bool(
                isinstance(row, dict)
                and row.get("source") == "notino_public_storefront"
                and row.get("currency") == "EUR"
                and row.get("currency_explicit") is True
                and row.get("availability") in {"in_stock", "out_of_stock"}
                and float(row.get("price") or 0) > 0
                and (row.get("size_ml") or row.get("sizeml"))
                and row.get("concentration")
                and row.get("brand")
                and row.get("url") == candidate.product_url
            )
            item["verified"] = valid
            if not valid:
                item["failed_checks"] = [
                    name for name, passed in {
                        "direct_source": isinstance(row, dict) and row.get("source") == "notino_public_storefront",
                        "explicit_eur": isinstance(row, dict) and row.get("currency") == "EUR" and row.get("currency_explicit") is True,
                        "explicit_stock": isinstance(row, dict) and row.get("availability") in {"in_stock", "out_of_stock"},
                        "positive_price": isinstance(row, dict) and float(row.get("price") or 0) > 0,
                        "perfume_identity": isinstance(row, dict) and bool((row.get("size_ml") or row.get("sizeml")) and row.get("concentration") and row.get("brand")),
                        "exact_product_url": isinstance(row, dict) and row.get("url") == candidate.product_url,
                    }.items() if not passed
                ]
            verified += int(valid)
            report.append(item)
        except Exception as exc:
            report.append({
                "candidate_name": candidate.raw_payload.get("name"),
                "candidate_query": candidate.raw_payload.get("query"),
                "url": candidate.product_url,
                "verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            })

    result = {
        "mode": "direct_notino_public_storefront",
        "database_touched": False,
        "cj_feed_used": False,
        "discovered": len(candidates),
        "verified": verified,
        "products": report,
    }
    print("NOTINO_DIRECT_CONNECTOR_SMOKE=" + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if verified >= 1 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))

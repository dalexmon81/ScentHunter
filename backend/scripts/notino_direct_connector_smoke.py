#!/usr/bin/env python3
"""Read-only live acceptance smoke for direct Notino discovery and product fetch.

Discovery queries deliberately exclude the Liquid Brun known-URL seed. This
smoke must prove that public storefront search discovers multiple products
across multiple brands before page-fetch validation can pass.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

# Do not let the connector's default Liquid Brun seed satisfy discovery.
DISCOVERY_QUERIES = (
    "Dior Sauvage Eau de Parfum",
    "Bleu de Chanel Eau de Parfum",
    "Yves Saint Laurent Y Eau de Parfum",
    "Acqua di Gio Profondo Eau de Parfum",
    "Afnan 9PM Eau de Parfum",
)
MIN_DISCOVERED = 3
MIN_DISTINCT_BRANDS = 3
MIN_VERIFIED = 3


def compact(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {"result": "not_found"}
    return {
        "name": row.get("name"),
        "brand": row.get("brand"),
        "size_ml": row.get("size_ml") or row.get("sizeml"),
        "concentration": row.get("concentration"),
        "gtin": row.get("gtin"),
        "price": row.get("price"),
        "currency": row.get("currency"),
        "currency_explicit": row.get("currency_explicit"),
        "availability": row.get("availability"),
        "url": row.get("url"),
        "source": row.get("source"),
    }


async def run() -> int:
    os.environ["SCENTHUNTER_DISCOVERY_QUERIES_NOTINO"] = ";".join(DISCOVERY_QUERIES)
    from app.connectors.notino_public import NotinoPublicStorefrontConnector

    connector = NotinoPublicStorefrontConnector()
    report: list[dict[str, Any]] = []
    try:
        candidates = await connector.discover_products(limit=20)
    except Exception as exc:
        result = {
            "mode": "direct_notino_public_storefront_discovery_acceptance",
            "database_touched": False,
            "cj_feed_used": False,
            "discovery_queries": list(DISCOVERY_QUERIES),
            "discovered": 0,
            "distinct_brands": 0,
            "verified": 0,
            "error": f"{type(exc).__name__}: {exc}",
            "products": [],
        }
        print("NOTINO_DIRECT_CONNECTOR_SMOKE=" + json.dumps(result, ensure_ascii=False), flush=True)
        return 1

    # Brand diversity is evaluated on fetched product evidence, not query labels
    # or URL slugs, which are not authoritative product identity.
    verified = 0
    verified_brands: set[str] = set()
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
            if valid:
                verified += 1
                verified_brands.add(str(row.get("brand")).strip().casefold())
            else:
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
            report.append(item)
        except Exception as exc:
            report.append({
                "candidate_name": candidate.raw_payload.get("name"),
                "candidate_query": candidate.raw_payload.get("query"),
                "url": candidate.product_url,
                "verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            })

    # A smoke is not green just because one hard-coded product page works.
    discovery_pass = len(candidates) >= MIN_DISCOVERED
    diversity_pass = len(verified_brands) >= MIN_DISTINCT_BRANDS
    fetch_pass = verified >= MIN_VERIFIED
    result = {
        "mode": "direct_notino_public_storefront_discovery_acceptance",
        "database_touched": False,
        "cj_feed_used": False,
        "discovery_queries": list(DISCOVERY_QUERIES),
        "discovered": len(candidates),
        "distinct_verified_brands": len(verified_brands),
        "verified": verified,
        "minimums": {
            "discovered": MIN_DISCOVERED,
            "distinct_verified_brands": MIN_DISTINCT_BRANDS,
            "verified": MIN_VERIFIED,
        },
        "acceptance": {
            "discovery": discovery_pass,
            "brand_diversity": diversity_pass,
            "product_fetch": fetch_pass,
        },
        "products": report,
    }
    print("NOTINO_DIRECT_CONNECTOR_SMOKE=" + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if discovery_pass and diversity_pass and fetch_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))

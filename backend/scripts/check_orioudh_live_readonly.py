#!/usr/bin/env python3
"""Read-only live smoke test for Orioudh's Shopify scraper.

This script makes public GET requests only. It does not import the database,
write catalog rows, or require application secrets.
"""
from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

from scrapers.orioudh import scraper


QUERY = "Liquid Brun"
EXPECTED_BRAND = "French Avenue"


def fail(message: str) -> int:
    print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False, indent=2))
    return 1


def main() -> int:
    report = scraper.search_stream(QUERY)
    if not isinstance(report, dict):
        return fail("search_stream returned a non-object report")
    if report.get("status") != "success" or report.get("verified") is not True:
        return fail(
            f"discovery/extraction not verified: status={report.get('status')!r}, "
            f"verified={report.get('verified')!r}, error={report.get('error')!r}"
        )

    rows = report.get("results")
    if not isinstance(rows, list) or not rows:
        return fail("verified discovery returned no Liquid Brun offers")

    matching = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = row.get("source") or {}
        offer = row.get("offer") or {}
        identity = row.get("identity") or {}
        attributes = row.get("attributes") or {}
        url = source.get("url") or row.get("url")
        parsed_url = urlparse(str(url or ""))
        brand = str(source.get("source_brand") or "").strip()
        name = str(source.get("source_name") or row.get("name") or "")
        price = offer.get("price")
        currency = offer.get("currency")
        availability = offer.get("availability")
        sku = identity.get("sku")
        gtin = identity.get("gtin")
        size = attributes.get("size_ml")
        concentration = attributes.get("concentration")

        if "liquid brun" not in name.lower() or EXPECTED_BRAND.lower() not in brand.lower():
            continue
        if parsed_url.scheme != "https" or parsed_url.netloc not in {"orioudh.com", "www.orioudh.com"}:
            continue
        if not parsed_url.path.startswith("/products/"):
            continue
        if not isinstance(price, (int, float)) or price <= 0:
            return fail(f"invalid parsed price for {name!r}: {price!r}")
        if currency != "EUR":
            return fail(f"unexpected currency for {name!r}: {currency!r}")
        if availability not in {"in_stock", "out_of_stock"}:
            return fail(f"availability is not explicitly parsed for {name!r}: {availability!r}")
        if not (isinstance(sku, dict) and sku.get("value") or isinstance(gtin, dict) and gtin.get("value")):
            return fail(f"neither SKU nor GTIN was extracted for {name!r}")
        if not (isinstance(size, dict) and size.get("value") == 100):
            return fail(f"100 ml size was not extracted for {name!r}: {size!r}")
        if not (isinstance(concentration, dict) and concentration.get("value") == "Eau de Parfum"):
            return fail(f"Eau de Parfum concentration was not extracted for {name!r}: {concentration!r}")

        matching.append({
            "name": name,
            "brand": brand,
            "url": url,
            "price": price,
            "currency": currency,
            "availability": availability,
            "sku": sku.get("value") if isinstance(sku, dict) else None,
            "gtin": gtin.get("value") if isinstance(gtin, dict) else None,
            "size_ml": size.get("value") if isinstance(size, dict) else None,
            "concentration": concentration.get("value") if isinstance(concentration, dict) else None,
        })

    if not matching:
        return fail("no extracted offer passed the Liquid Brun/French Avenue field checks")

    print(json.dumps({
        "status": "success",
        "verified": True,
        "read_only": True,
        "database_written": False,
        "query": QUERY,
        "offers_checked": len(rows),
        "matching_offers": matching,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

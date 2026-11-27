#!/usr/bin/env python3
"""Bounded, read-only live validation for Parfum-Zentrum discovery and extraction.

Uses the retailer's own search form for one fixed query, then fetches at most
three discovered product pages. No sitemap fallback, retries, proxy, browser,
database, catalog, queue, or Neon access.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from scrapers.parfumzentrum import scraper

QUERY = "Afnan 9 pm"
MAX_PRODUCT_FETCHES = 3


def _offers(product: dict[str, Any]) -> list[dict[str, Any]]:
    offers = product.get("offers")
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [item for item in offers if isinstance(item, dict)]
    return []


def _explicit_eur(product: dict[str, Any], parsed_price: Any) -> bool:
    for offer in _offers(product):
        currency = str(offer.get("priceCurrency") or "").strip().upper()
        raw_price = offer.get("price") or offer.get("lowPrice")
        try:
            evidence_price = Decimal(str(raw_price))
            actual_price = Decimal(str(parsed_price))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if currency == "EUR" and evidence_price == actual_price:
            return True
    return False


def main() -> int:
    report: dict[str, Any] = {
        "mode": "parfumzentrum_bounded_live_read_only",
        "query": QUERY,
        "discovered_candidates": 0,
        "product_pages_fetched": 0,
        "verified_products": 0,
        "products": [],
        "database_accessed": False,
        "catalog_written": False,
        "queue_touched": False,
        "neon_accessed": False,
        "sitemap_used": False,
        "retries": 0,
    }
    try:
        candidates = scraper._discover_from_store_search_form(QUERY)
        report["discovered_candidates"] = len(candidates)
        for url in candidates[:MAX_PRODUCT_FETCHES]:
            report["product_pages_fetched"] += 1
            try:
                row = scraper._extract_product(url, QUERY)
            except Exception as exc:
                report["products"].append({
                    "url": url,
                    "verified": False,
                    "error": type(exc).__name__,
                })
                continue
            if not isinstance(row, dict):
                report["products"].append({"url": url, "verified": False, "reason": "page_not_verified"})
                continue

            jsonld = row.get("raw_data", {}).get("jsonld", {})
            brand = row.get("brand")
            size = row.get("size_ml")
            price = row.get("price_num")
            currency_explicit = _explicit_eur(jsonld if isinstance(jsonld, dict) else {}, price)
            availability = row.get("availability")
            url_matches = row.get("url") == url
            valid = bool(
                brand
                and size
                and row.get("concentration")
                and price is not None
                and float(price) > 0
                and currency_explicit
                and availability in {"in_stock", "out_of_stock"}
                and url_matches
            )
            report["verified_products"] += int(valid)
            report["products"].append({
                "name": row.get("name"),
                "brand": brand,
                "size_ml": size,
                "concentration": row.get("concentration"),
                "gtin": row.get("gtin"),
                "price": f"{float(price):.2f}" if price is not None else None,
                "currency": "EUR" if currency_explicit else None,
                "currency_explicit": currency_explicit,
                "availability": availability,
                "url": row.get("url"),
                "verified": valid,
            })
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["status"] = (
        "VERIFIED_PRODUCT_FOUND"
        if report["verified_products"] > 0
        else "NO_VERIFIED_PRODUCT"
    )
    print("PARFUMZENTRUM_LIVE_PROBE=" + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["verified_products"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Bounded, read-only multi-brand live validation for Parfum-Zentrum.

Uses the retailer's own search form for three fixed, independent brand queries,
then fetches at most two discovered product pages per query. No sitemap fallback,
retries, proxy, browser, database, catalog, queue, or Neon access.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Any

from scrapers.parfumzentrum import scraper

QUERIES = ("Afnan 9 pm", "Dior Eau Sauvage Parfum 2017 Eau de Parfum", "Davidoff Cool Water")
MAX_PRODUCT_FETCHES_PER_QUERY = 2
MIN_DISTINCT_BRANDS = 3


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
        "mode": "parfumzentrum_bounded_multi_brand_live_read_only",
        "queries": list(QUERIES),
        "discovered_candidates": 0,
        "product_pages_fetched": 0,
        "verified_products": 0,
        "distinct_verified_brands": [],
        "query_reports": [],
        "database_accessed": False,
        "catalog_written": False,
        "queue_touched": False,
        "neon_accessed": False,
        "sitemap_used": False,
        "retries": 0,
    }
    brands: set[str] = set()
    try:
        for query in QUERIES:
            query_report: dict[str, Any] = {
                "query": query,
                "discovered_candidates": 0,
                "product_pages_fetched": 0,
                "verified_products": 0,
                "products": [],
            }
            candidates = scraper._discover_from_store_search_form(query)
            query_report["discovered_candidates"] = len(candidates)
            report["discovered_candidates"] += len(candidates)

            for url in candidates[:MAX_PRODUCT_FETCHES_PER_QUERY]:
                report["product_pages_fetched"] += 1
                query_report["product_pages_fetched"] += 1
                try:
                    row = scraper._extract_product(url, query)
                except Exception as exc:
                    query_report["products"].append({
                        "url": url,
                        "verified": False,
                        "error": type(exc).__name__,
                    })
                    continue
                if not isinstance(row, dict):
                    query_report["products"].append({
                        "url": url,
                        "verified": False,
                        "reason": "page_not_verified",
                    })
                    continue

                raw_data = row.get("raw_data")
                jsonld = raw_data.get("jsonld") if isinstance(raw_data, dict) else {}
                jsonld = jsonld if isinstance(jsonld, dict) else {}
                brand = str(row.get("brand") or "").strip()
                size = row.get("size_ml")
                price = row.get("price_num")
                currency_explicit = _explicit_eur(jsonld, price)
                availability = row.get("availability")
                valid = bool(
                    brand
                    and size
                    and row.get("concentration")
                    and price is not None
                    and float(price) > 0
                    and currency_explicit
                    and availability in {"in_stock", "out_of_stock"}
                    and row.get("url") == url
                )
                query_report["products"].append({
                    "name": row.get("name"),
                    "brand": brand or None,
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
                if valid:
                    query_report["verified_products"] += 1
                    report["verified_products"] += 1
                    brands.add(brand.casefold())
            report["query_reports"].append(query_report)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["distinct_verified_brands"] = sorted(brands)
    report["status"] = (
        "VERIFIED_THREE_BRANDS"
        if len(brands) >= MIN_DISTINCT_BRANDS
        else "PARTIAL_MULTI_BRAND_COVERAGE"
        if brands
        else "NO_VERIFIED_PRODUCT"
    )
    print("PARFUMZENTRUM_LIVE_PROBE=" + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if len(brands) >= MIN_DISTINCT_BRANDS else 1


if __name__ == "__main__":
    sys.exit(main())

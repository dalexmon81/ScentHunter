#!/usr/bin/env python3
"""Bounded, read-only multi-brand discovery acceptance for Deloox.be.

Uses only Deloox's own public search surface and fetches at most two product
pages per independent query. No sitemap/category fallback, retries, database,
catalog, queue, Neon, or deployment access.
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from scrapers.deloox import scraper

QUERIES = (
    ("Afnan 9PM Eau de Parfum", "afnan"),
    ("Dior Sauvage Eau de Parfum", "dior"),
    ("Davidoff Cool Water Eau de Toilette", "davidoff"),
)
MAX_PAGES_PER_QUERY = 2
MIN_VERIFIED = 3
MIN_DISTINCT_BRANDS = 3


def explicit_eur_for_price(record: dict[str, Any]) -> bool:
    offer = record.get("offer") if isinstance(record.get("offer"), dict) else {}
    raw = record.get("raw_data") if isinstance(record.get("raw_data"), dict) else {}
    jsonld = raw.get("jsonld") if isinstance(raw.get("jsonld"), dict) else {}
    offers = jsonld.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    try:
        normalized_price = Decimal(str(offer.get("price")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("priceCurrency") or "").strip().upper() == "EUR"
        and _decimal(item.get("price")) == normalized_price
        for item in offers
    )


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def main() -> int:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/ms-playwright"
    report: dict[str, Any] = {
        "mode": "deloox_be_bounded_multi_brand_live_read_only",
        "queries": [query for query, _ in QUERIES],
        "discovered_candidates": 0,
        "product_pages_fetched": 0,
        "verified_products": 0,
        "distinct_verified_brands": [],
        "query_reports": [],
        "database_accessed": False,
        "catalog_written": False,
        "queue_touched": False,
        "neon_accessed": False,
        "category_fallback_used": False,
        "sitemap_fallback_used": False,
        "retries": 0,
    }
    brands: set[str] = set()
    seen_urls: set[str] = set()

    try:
        with requests.Session() as session:
            session.headers.update(scraper.HEADERS)
            for query, expected_brand in QUERIES:
                query_report: dict[str, Any] = {
                    "query": query,
                    "expected_brand": expected_brand,
                    "discovered_candidates": 0,
                    "product_pages_fetched": 0,
                    "verified_products": [],
                    "candidate_urls": [],
                }
                deadline = time.monotonic() + 25
                candidates = scraper._discover_from_search(
                    session, query, deadline=deadline
                )
                candidates = list(dict.fromkeys(candidates or []))
                query_report["discovered_candidates"] = len(candidates)
                query_report["candidate_urls"] = candidates[:MAX_PAGES_PER_QUERY]
                report["discovered_candidates"] += len(candidates)

                for url in candidates[:MAX_PAGES_PER_QUERY]:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    report["product_pages_fetched"] += 1
                    query_report["product_pages_fetched"] += 1
                    try:
                        row = scraper.extract_product_page(session, url, query=query)
                    except Exception as exc:
                        query_report.setdefault("errors", []).append(
                            {"url": url, "error": f"{type(exc).__name__}: {exc}"}
                        )
                        continue
                    if not isinstance(row, dict):
                        continue

                    source = row.get("source") if isinstance(row.get("source"), dict) else {}
                    attributes = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
                    offer = row.get("offer") if isinstance(row.get("offer"), dict) else {}
                    size = attributes.get("size_ml") if isinstance(attributes.get("size_ml"), dict) else {}
                    strength = attributes.get("concentration") if isinstance(attributes.get("concentration"), dict) else {}
                    brand = str(source.get("source_brand") or "").strip()
                    name = str(row.get("name") or "").strip()
                    price = _decimal(offer.get("price"))
                    valid = bool(
                        brand.casefold() == expected_brand
                        and scraper.matches(name, query)
                        and size.get("value") is not None
                        and strength.get("value")
                        and price is not None and price > 0
                        and str(offer.get("currency") or "").strip().upper() == "EUR"
                        and explicit_eur_for_price(row)
                        and offer.get("availability") == "in_stock"
                        and source.get("url") == url
                        and scraper._is_deloox_url(url)
                    )
                    product = {
                        "name": name or None,
                        "brand": brand or None,
                        "size_ml": size.get("value"),
                        "concentration": strength.get("value"),
                        "gtin": ((row.get("identity") or {}).get("gtin") or {}).get("value")
                            if isinstance((row.get("identity") or {}).get("gtin"), dict) else None,
                        "price": str(price) if price is not None else None,
                        "currency": "EUR" if explicit_eur_for_price(row) else None,
                        "availability": offer.get("availability"),
                        "url": source.get("url"),
                        "verified": valid,
                    }
                    query_report.setdefault("products", []).append(product)
                    if valid:
                        report["verified_products"] += 1
                        query_report["verified_products"].append(product)
                        brands.add(brand.casefold())
                report["query_reports"].append(query_report)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["distinct_verified_brands"] = sorted(brands)
    report["acceptance"] = {
        "minimum_verified_products": MIN_VERIFIED,
        "minimum_distinct_brands": MIN_DISTINCT_BRANDS,
        "product_count": report["verified_products"] >= MIN_VERIFIED,
        "brand_diversity": len(brands) >= MIN_DISTINCT_BRANDS,
    }
    report["status"] = (
        "VERIFIED_THREE_BRANDS"
        if report["acceptance"]["product_count"] and report["acceptance"]["brand_diversity"]
        else "PARTIAL_MULTI_BRAND_COVERAGE"
        if report["verified_products"]
        else "NO_VERIFIED_PRODUCT"
    )
    print("DELOOX_MULTI_PRODUCT_LIVE=" + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "VERIFIED_THREE_BRANDS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

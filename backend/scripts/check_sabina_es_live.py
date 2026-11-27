#!/usr/bin/env python3
"""Bounded read-only live validation of Sabina's Spanish storefront.

Uses only Sabina's native Spanish search endpoint (one request per query),
then fetches at most two /es/ product pages per query. No Sellboost/Italian
fallback, sitemap, browser, retries, database, catalog, queue, or Neon access.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import requests

from scrapers.sabina import scraper

QUERIES = ("Afnan 9 pm", "Dior Sauvage", "Davidoff Cool Water")
MAX_PRODUCT_FETCHES_PER_QUERY = 2


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _explicit_matching_eur(product: dict[str, Any], selected_offer: Any) -> bool:
    if not isinstance(selected_offer, dict):
        return False
    selected_price = _decimal(selected_offer.get("price"))
    if selected_offer.get("currency") != "EUR" or selected_price is None:
        return False
    jsonld = product.get("raw_data", {}).get("jsonld_product")
    if not isinstance(jsonld, dict):
        return False
    offers = scraper._offer_list(jsonld)
    return any(
        str(item.get("priceCurrency") or "").strip().upper() == "EUR"
        and _decimal(item.get("price")) == selected_price
        for item in offers
    )


def main() -> int:
    report: dict[str, Any] = {
        "mode": "sabina_es_native_search_read_only",
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
        "sellboost_used": False,
        "sitemap_used": False,
        "browser_used": False,
        "retries": 0,
    }
    brands: set[str] = set()
    session = requests.Session()
    try:
        for query in QUERIES:
            qr: dict[str, Any] = {
                "query": query,
                "search_requests": 1,
                "discovered_candidates": 0,
                "product_pages_fetched": 0,
                "verified_products": 0,
                "products": [],
            }
            try:
                response = session.get(
                    scraper.SEARCH_ENDPOINTS[0][0],
                    params={"search_query": query},
                    headers=scraper.HEADERS,
                    timeout=scraper.DISCOVERY_TIMEOUT,
                    allow_redirects=True,
                )
                try:
                    if response.status_code >= 400:
                        qr["search_error"] = f"http_{response.status_code}"
                        report["query_reports"].append(qr)
                        continue
                    candidates = scraper._extract_search_candidates(response, query)
                finally:
                    response.close()
            except requests.RequestException as exc:
                qr["search_error"] = type(exc).__name__
                report["query_reports"].append(qr)
                continue

            candidates = [
                url for url in candidates
                if (urlparse(url).hostname or "").lower() in {"sabina.com", "www.sabina.com"}
                and urlparse(url).path.lower().startswith("/es/")
            ]
            qr["discovered_candidates"] = len(candidates)
            report["discovered_candidates"] += len(candidates)

            for url in candidates[:MAX_PRODUCT_FETCHES_PER_QUERY]:
                qr["product_pages_fetched"] += 1
                report["product_pages_fetched"] += 1
                try:
                    row = scraper.extract_product_page(session, url, query)
                except Exception as exc:
                    qr["products"].append({"url": url, "verified": False, "error": type(exc).__name__})
                    continue
                if not isinstance(row, dict):
                    qr["products"].append({"url": url, "verified": False, "reason": "page_not_verified"})
                    continue

                selected_offer = row.get("offer")
                currency_explicit = _explicit_matching_eur(row, selected_offer)
                brand = str(row.get("brand") or "").strip()
                offer = selected_offer if isinstance(selected_offer, dict) else {}
                price = _decimal(offer.get("price"))
                availability = offer.get("availability")
                size = scraper._identity_value(row.get("attributes", {}).get("size_ml")) if isinstance(row.get("attributes"), dict) else None
                concentration = scraper._identity_value(row.get("attributes", {}).get("concentration")) if isinstance(row.get("attributes"), dict) else None
                product_url = row.get("url")
                valid = bool(
                    brand and size and concentration and price is not None and price > 0
                    and currency_explicit
                    and availability in {"in_stock", "out_of_stock"}
                    and product_url == url
                    and urlparse(product_url).path.lower().startswith("/es/")
                )
                qr["products"].append({
                    "name": row.get("name"),
                    "brand": brand or None,
                    "size_ml": size,
                    "concentration": concentration,
                    "gtin": scraper._identity_value(row.get("identity", {}).get("gtin")) if isinstance(row.get("identity"), dict) else None,
                    "price": str(price) if price is not None else None,
                    "currency": "EUR" if currency_explicit else None,
                    "currency_explicit": currency_explicit,
                    "availability": availability,
                    "url": product_url,
                    "verified": valid,
                })
                if valid:
                    qr["verified_products"] += 1
                    report["verified_products"] += 1
                    brands.add(brand.casefold())
            report["query_reports"].append(qr)
    finally:
        session.close()

    report["distinct_verified_brands"] = sorted(brands)
    report["status"] = "VERIFIED_THREE_BRANDS" if len(brands) >= 3 else (
        "PARTIAL_MULTI_BRAND_COVERAGE" if brands else "NO_VERIFIED_PRODUCT"
    )
    print("SABINA_ES_LIVE_PROBE=" + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if len(brands) >= 3 else 1


if __name__ == "__main__":
    sys.exit(main())

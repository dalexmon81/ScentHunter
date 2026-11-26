#!/usr/bin/env python3
"""Read-only live check that Orioudh's displayed price proves its currency."""
from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

import requests

from scrapers.orioudh import scraper


QUERY = "Liquid Brun"
EXPECTED_BRAND = "French Avenue"
ALLOWED_EVIDENCE = {
    "jsonld_offer_price",
    "product_price_meta",
    "product_price_display",
}


def decimal_value(value):
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None


def fail(message):
    print(json.dumps({"status": "failed", "error": message}, ensure_ascii=False, indent=2))
    return 1


def main() -> int:
    report = scraper.search_stream(QUERY)
    if not isinstance(report, dict) or report.get("status") != "success" or report.get("verified") is not True:
        return fail(f"unverified Orioudh discovery: {report!r}")

    rows = report.get("results")
    if not isinstance(rows, list):
        return fail("discovery results are not a list")

    target = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = row.get("source") or {}
        identity = row.get("identity") or {}
        attributes = row.get("attributes") or {}
        name = str(source.get("source_name") or row.get("name") or "")
        brand = str(source.get("source_brand") or "")
        size = attributes.get("size_ml") or {}
        variant = identity.get("store_variant_id") or {}
        if (
            "liquid brun" in name.lower()
            and EXPECTED_BRAND.lower() in brand.lower()
            and "limited edition" not in name.lower()
            and isinstance(size, dict)
            and size.get("value") == 100
            and isinstance(variant, dict)
            and variant.get("value") not in (None, "")
        ):
            target = row
            break

    if target is None:
        return fail("standard 100 ml Liquid Brun variant was not discovered")

    source = target.get("source") or {}
    identity = target.get("identity") or {}
    variant = identity.get("store_variant_id") or {}
    product_url = str(source.get("url") or target.get("url") or "")
    variant_id = str(variant.get("value"))
    offer = target.get("offer") or {}
    expected_price = decimal_value(offer.get("price"))
    if not product_url.startswith("https://orioudh.com/products/") or expected_price is None:
        return fail("invalid canonical product URL or parsed variant price")

    variant_url = product_url + "?" + urlencode({"variant": variant_id})
    session = requests.Session()
    try:
        records = scraper.extract_product_page(session, variant_url, query=QUERY)
    finally:
        session.close()

    matching = [
        row for row in records
        if str((((row.get("identity") or {}).get("store_variant_id") or {}).get("value"))) == variant_id
    ]
    if len(matching) != 1:
        return fail(f"expected one fetched variant {variant_id}, found {len(matching)}")

    fetched = matching[0]
    fetched_offer = fetched.get("offer") or {}
    evidence = (fetched.get("raw_data") or {}).get("currency_evidence")
    if not isinstance(evidence, dict):
        return fail("no explicit currency evidence found on the selected product page")
    if evidence.get("source") not in ALLOWED_EVIDENCE:
        return fail(f"currency evidence source is not accepted: {evidence.get('source')!r}")
    if evidence.get("currency") != "EUR" or fetched_offer.get("currency") != "EUR":
        return fail(f"currency mismatch: evidence={evidence!r}, offer={fetched_offer!r}")
    if decimal_value(evidence.get("matched_price")) != decimal_value(fetched_offer.get("price")):
        return fail(f"currency evidence price does not match selected variant: {evidence!r}")
    if decimal_value(fetched_offer.get("price")) != expected_price:
        return fail("selected variant price changed between discovery and direct fetch")

    print(json.dumps({
        "status": "success",
        "verified": True,
        "read_only": True,
        "database_written": False,
        "product_url": product_url,
        "variant_id": variant_id,
        "price": str(expected_price),
        "currency": "EUR",
        "currency_evidence": evidence,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

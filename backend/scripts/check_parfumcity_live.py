from __future__ import annotations

import json
import sys
from decimal import Decimal
from urllib.parse import urlparse

import requests

from scrapers.parfumcity import scraper


def fail(message: str) -> None:
    print(f"PARFUMCITY_LIVE_AUDIT=FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    query = "Liquid Brun"
    report = scraper.search_stream(query)
    if not report.get("verified") or report.get("status") not in {"success", "partial"}:
        fail(f"discovery not verified: {report.get('status')} {report.get('error')}")
    discovered = report.get("results") or []
    if not discovered:
        fail(f"discovery returned no products; details={report.get('details')}")

    session = requests.Session()
    try:
        selected = None
        extracted = None
        for candidate in discovered:
            url = str(candidate.get("url") or "").strip()
            parsed = urlparse(url)
            variant_id = (
                candidate.get("identity", {})
                .get("store_variant_id", {})
                .get("value")
            )
            if parsed.scheme != "https" or parsed.hostname not in {"parfumcity.nl", "www.parfumcity.nl"}:
                continue
            if variant_id in (None, ""):
                continue
            records = scraper.extract_product_page(session, url, query=query)
            matches = [
                row for row in records
                if str(row.get("identity", {}).get("store_variant_id", {}).get("value") or "") == str(variant_id)
            ]
            if len(matches) == 1:
                selected, extracted = candidate, matches[0]
                break

        if selected is None or extracted is None:
            fail("no discovered Shopify variant could be re-fetched exactly")

        price = Decimal(str(extracted.get("price_num") or "0"))
        offer = extracted.get("offer") or {}
        raw_data = extracted.get("raw_data") or {}
        evidence = raw_data.get("currency_evidence") or {}
        if price <= 0:
            fail("extracted price is missing or invalid")
        if offer.get("currency") != "EUR" or evidence.get("currency") != "EUR":
            fail(f"EUR currency evidence missing: offer={offer.get('currency')} evidence={evidence}")
        if Decimal(str(evidence.get("matched_price") or "0")) != price:
            fail("currency evidence does not match the exact extracted price")
        if extracted.get("availability") not in {"in_stock", "out_of_stock"}:
            fail(f"availability is not explicit: {extracted.get('availability')}")
        url = str(extracted.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"parfumcity.nl", "www.parfumcity.nl"}:
            fail(f"invalid product URL: {url}")

        result = {
            "query": query,
            "discovery_candidates": len(discovered),
            "product": extracted.get("name"),
            "brand": extracted.get("brand"),
            "variant_id": extracted.get("identity", {}).get("store_variant_id", {}).get("value"),
            "size_ml": extracted.get("size_ml"),
            "price": str(price),
            "currency": offer.get("currency"),
            "availability": extracted.get("availability"),
            "url": url,
            "currency_evidence_source": evidence.get("source"),
            "shopify_vendor": (extracted.get("raw_data") or {}).get("product", {}).get("vendor"),
            "shopify_product_type": (extracted.get("raw_data") or {}).get("product", {}).get("product_type"),
            "shopify_tags": (extracted.get("raw_data") or {}).get("product", {}).get("tags"),
            "description_text": " ".join(
                __import__("bs4").BeautifulSoup(
                    str((extracted.get("raw_data") or {}).get("product", {}).get("body_html") or ""),
                    "html.parser",
                ).stripped_strings
            )[:1000],
        }
        print("PARFUMCITY_LIVE_AUDIT=" + json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only live validation of the Bplatz Liquid Brun pilot offer."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from catalog_engine import parse_product as parse_worker_product  # noqa: E402
from scrapers.bplatz.scraper import HEADERS, parse_product_html  # noqa: E402
from scenthunter_next_engine.next_engine_service import NextEngineService  # noqa: E402
from scenthunter_next_engine.offer_normalizer import normalize_offer  # noqa: E402


PRODUCT_URL = (
    "https://bplatz.de/products/fragrance-world-liquid-brun-eau-de-parfum-100ml"
    "?variant=54015243419916"
)
CANONICAL_PRODUCT_ID = "SH-0030"
CANONICAL_VARIANT_ID = "VAR-f87146c82d167f4c"


def build_report(parsed: dict, worker_item: dict, captured_at: datetime) -> dict:
    if "liquid brun" not in str(parsed.get("name", "")).casefold():
        raise RuntimeError("Bplatz page did not identify Liquid Brun")
    if str(parsed.get("brand", "")).casefold() != "french avenue":
        raise RuntimeError("Bplatz page did not identify the French Avenue brand")
    if parsed.get("size_ml") != 100:
        raise RuntimeError("Bplatz page did not identify the 100 ml variant")
    if worker_item.get("currency_explicit") is not True:
        raise RuntimeError("Bplatz page did not provide explicit currency")

    record = {
        "raw_name": parsed["name"],
        "brand_raw": parsed["brand"],
        "size_ml": parsed["size_ml"],
        "price": parsed["price_num"],
        "currency": parsed["offer"]["currency"],
        "currency_explicit": worker_item["currency_explicit"],
        "product_url": parsed["url"],
        "availability": parsed["availability"],
        "sku": parsed["sku"],
        "gtin": parsed["gtin"],
    }
    offer = normalize_offer(record, retailer="Bplatz", currency_default="EUR")
    if offer.price is None or offer.price <= 0:
        raise RuntimeError("Bplatz page did not provide a positive price")
    if offer.currency != "EUR":
        raise RuntimeError("Bplatz offer currency is not EUR")
    if offer.availability != "in_stock":
        raise RuntimeError(
            "Bplatz page did not confirm in-stock availability "
            f"(normalized={offer.availability!r}, parsed={parsed.get('availability')!r}, "
            f"worker_available={worker_item.get('available')!r}, "
            f"worker_availability={worker_item.get('availability')!r})"
        )

    parsed_url = urlsplit(offer.product_url or "")
    host = (parsed_url.hostname or "").lower().rstrip(".")
    if (
        parsed_url.scheme != "https"
        or not (host == "bplatz.de" or host.endswith(".bplatz.de"))
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise RuntimeError("Bplatz page returned an invalid product URL")

    matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
    result = matcher.process_offers([offer])
    if result.matched_offer_count != 1 or len(result.groups) != 1:
        raise RuntimeError("Bplatz offer did not resolve to one canonical variant")
    match = result.groups[0]
    if (
        match.canonical_product_id != CANONICAL_PRODUCT_ID
        or match.canonical_variant_id != CANONICAL_VARIANT_ID
    ):
        raise RuntimeError("Bplatz offer matched a different canonical product variant")

    return {
        "status": "verified",
        "store": "Bplatz",
        "brand": "French Avenue",
        "product": "Liquid Brun",
        "size_ml": 100,
        "price": str(offer.price),
        "currency": offer.currency,
        "availability": offer.availability,
        "url": offer.product_url,
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "canonical_product_id": match.canonical_product_id,
        "canonical_variant_id": match.canonical_variant_id,
        "raw_record": record,
        "database_written": False,
    }


def fetch_live_offer() -> dict:
    with requests.Session() as session:
        response = session.get(PRODUCT_URL, headers=HEADERS, timeout=(5, 20))
        response.raise_for_status()
        html = response.content
        final_url = response.url
        response.close()

    parsed = parse_product_html(
        html.decode("utf-8", errors="replace"),
        final_url,
        "French Avenue Liquid Brun",
    )
    worker_item = parse_worker_product("bplatz", final_url, html)
    if parsed is None or worker_item is None:
        raise RuntimeError("Bplatz page could not be parsed as Liquid Brun")
    return build_report(parsed, worker_item, datetime.now(timezone.utc))


def main() -> int:
    try:
        report = fetch_live_offer()
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(json.dumps({
            "status": "failed",
            "reason": str(exc),
            "database_written": False,
        }, ensure_ascii=False))
        return 1

    print("BPLATZ_LIQUID_BRUN_LIVE_CHECK=" + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

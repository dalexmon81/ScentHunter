"""Read-only live Bplatz discovery, extraction and canonical matching probe."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from scrapers.bplatz.scraper import search_stream  # noqa: E402
from catalog_engine import parse_product as parse_worker_product  # noqa: E402
from scenthunter_next_engine.next_engine_service import NextEngineService  # noqa: E402
from scenthunter_next_engine.offer_normalizer import normalize_offer  # noqa: E402

def main() -> int:
    report = search_stream("Liquid Brun")
    rows = report.get("results") or []
    output = {
        "store": "Bplatz",
        "query": "Liquid Brun",
        "discovery_status": report.get("status"),
        "discovery_verified": report.get("details", {}).get("discovery_verified"),
        "candidate_count": report.get("details", {}).get("candidate_count"),
        "discovery_errors": report.get("details", {}).get("discovery_errors", []),
        "products": [],
        "database_written": False,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
    for row in rows:
        url = row.get("url")
        worker_item = parse_worker_product("bplatz", url, None)
        if not worker_item:
            # Fetch through the worker parser's normal URL path, not a fabricated fixture.
            import requests
            from scrapers.bplatz.scraper import HEADERS
            with requests.Session() as session:
                response = session.get(url, headers=HEADERS, timeout=(5, 20))
                response.raise_for_status()
                worker_item = parse_worker_product("bplatz", response.url, response.content)
                response.close()
        record = {
            "raw_name": row.get("name"),
            "brand_raw": row.get("brand"),
            "size_ml": row.get("size_ml"),
            "price": row.get("price_num"),
            "currency": row.get("currency"),
            "currency_explicit": worker_item.get("currency_explicit") is True,
            "product_url": row.get("url"),
            "availability": row.get("availability"),
            "sku": row.get("sku"),
            "gtin": row.get("gtin"),
        }
        offer = normalize_offer(record, retailer="Bplatz", currency_default="EUR")
        matches = matcher.process_offers([offer])
        matched = matches.matched_offer_count == 1 and len(matches.groups) == 1
        product = {
            "name": row.get("name"), "brand": row.get("brand"),
            "size_ml": row.get("size_ml"), "price": str(offer.price) if offer.price is not None else None,
            "currency": offer.currency, "availability": offer.availability,
            "url": offer.product_url, "gtin": row.get("gtin"), "sku": row.get("sku"),
            "canonical_match": matched,
        }
        if matched:
            product["canonical_product_id"] = matches.groups[0].canonical_product_id
            product["canonical_variant_id"] = matches.groups[0].canonical_variant_id
        output["products"].append(product)
    print("BPLATZ_LIVE_DISCOVERY=" + json.dumps(output, ensure_ascii=False))
    if not output["discovery_verified"] or not rows:
        return 1
    if not any(p["canonical_match"] for p in output["products"]):
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

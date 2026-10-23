"""Bounded live retailer parser probe; public HTTP only, no database access."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from backend.scrapers.deloox import scraper as deloox
from backend.scrapers.parfumzentrum import scraper as parfumzentrum

QUERY = "Acqua di Gio Profondo"
REPORT = Path("live-retailer-parser-probe.json")
KNOWN_URLS = {
    "easycosmetic_profondo": "https://www.easycosmetic.de/giorgio-armani/acqua-di-gio-homme-profondo/giorgio-armani-acqua-di-gio-homme-profondo-edp-vapo.aspx",
    "perfumemarket_profondo_125": "https://perfumemarket.nl/products/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-spray-125ml",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ScentHunterReadOnlyParserProbe/1.0)"}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def page_probe(url):
    result = {"url": url, "http_status": None, "title": None, "h1": None, "products": [], "error": None}
    try:
        response = requests.get(url, headers=HEADERS, timeout=(4, 10), allow_redirects=True)
        result["http_status"] = response.status_code
        result["final_url"] = response.url
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        result["title"] = clean(soup.title.get_text(" ", strip=True)) if soup.title else None
        h1 = soup.find("h1")
        result["h1"] = clean(h1.get_text(" ", strip=True)) if h1 else None
        for node in soup.select('script[type="application/ld+json"]')[:20]:
            try:
                data = json.loads(node.string or node.get_text())
            except (ValueError, TypeError):
                continue
            objects = data if isinstance(data, list) else [data]
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                nested = obj.get("@graph", [])
                for product in [obj] + (nested if isinstance(nested, list) else []):
                    if not isinstance(product, dict):
                        continue
                    types = product.get("@type", [])
                    if isinstance(types, str):
                        types = [types]
                    if "Product" not in types:
                        continue
                    offer = product.get("offers")
                    if isinstance(offer, list):
                        offer = offer[0] if offer else None
                    result["products"].append({
                        "name": product.get("name"),
                        "brand": product.get("brand"),
                        "gtin13": product.get("gtin13"),
                        "gtin": product.get("gtin"),
                        "sku": product.get("sku"),
                        "offers": {k: offer.get(k) for k in ("price", "priceCurrency", "availability")} if isinstance(offer, dict) else None,
                    })
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + clean(exc)[:240]
    return result


def adapter_probe(module):
    started = time.monotonic()
    try:
        rows = module.search(QUERY) or []
        clean_rows = []
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            attributes = row.get("attributes") or {}
            size = attributes.get("size_ml") or {}
            offer = row.get("offer") or {}
            identity = row.get("identity") or {}
            gtin = identity.get("gtin") or {}
            concentration = attributes.get("concentration") or {}
            clean_rows.append({
                "name": row.get("name") or row.get("title"),
                "url": row.get("url") or row.get("product_url"),
                "size_ml": row.get("size_ml") if row.get("size_ml") is not None else (size.get("value") if isinstance(size, dict) else None),
                "concentration": row.get("concentration") or (concentration.get("value") if isinstance(concentration, dict) else concentration),
                "price": offer.get("price", row.get("price_num", row.get("price"))),
                "availability": offer.get("availability", row.get("availability")),
                "gtin": gtin.get("value") if isinstance(gtin, dict) else row.get("gtin"),
            })
        return {"status": "results" if clean_rows else "zero_results", "rows": clean_rows,
                "row_count": len(rows), "elapsed_seconds": round(time.monotonic() - started, 2)}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__ + ": " + clean(exc)[:240],
                "elapsed_seconds": round(time.monotonic() - started, 2)}


def main():
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "scope": "Bounded public retailer HTTP and existing scraper adapters only. No production database, catalog writes, or deployment.",
        "known_page_probes": {name: page_probe(url) for name, url in KNOWN_URLS.items()},
        "deloox_adapter": adapter_probe(deloox),
        "parfumzentrum_adapter": adapter_probe(parfumzentrum),
    }
    # Separate transport/retailer blocking from parser extraction results.
    report["diagnosis"] = {
        "page_probe_summary": {
            name: {
                "http_status": item.get("http_status"),
                "has_product_jsonld": bool(item.get("products")),
                "jsonld_product_count": len(item.get("products") or []),
                "error_type": (item.get("error") or "").split(":", 1)[0] or None,
            }
            for name, item in report["known_page_probes"].items()
        },
        "adapter_summary": {
            "deloox": {
                "status": report["deloox_adapter"].get("status"),
                "parsed_row_count": report["deloox_adapter"].get("row_count", 0),
            },
            "parfumzentrum": {
                "status": report["parfumzentrum_adapter"].get("status"),
                "parsed_row_count": report["parfumzentrum_adapter"].get("row_count", 0),
            },
        },
        "interpretation": "HTTP blocking/errors are transport outcomes, not parser failures. Adapter rows show current live scraper output. This probe is diagnostic and does not claim canonical variant ownership.",
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

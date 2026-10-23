"""Bounded live retailer parser probe; public HTTP only, no database access."""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from backend.scrapers.deloox import scraper as deloox
from backend.scrapers.easycosmetic import scraper as easycosmetic
from backend.scrapers.parfumzentrum import scraper as parfumzentrum

QUERY = "Acqua di Gio Profondo"
REPORT = Path("live-retailer-parser-probe.json")
KNOWN_URLS = {
    "easycosmetic_profondo": ("https://www.easycosmetic.de/giorgio-armani/acqua-di-gio-homme-profondo/giorgio-armani-acqua-di-gio-homme-profondo-edp-vapo.aspx", "easycosmetic"),
    "perfumemarket_profondo_125": ("https://perfumemarket.nl/products/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-spray-125ml", None),
    "deloox_profondo_edp_30": ("https://www.deloox.be/produit/1321602/armani-acqua-di-gio-profondo-eau-de-parfum-30-ml.html", "deloox"),
    "deloox_profondo_edp_100": ("https://www.deloox.be/produit/1323846/armani-acqua-di-gio-profondo-eau-de-parfum-100-ml.html", "deloox"),
    "parfumzentrum_profondo_edp_125": ("https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-125-ml-man_z771966/", "parfumzentrum"),
    "parfumzentrum_profondo_edp_100_refill": ("https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-nachfullbar-100-ml-man_z947818/", "parfumzentrum"),
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ScentHunterReadOnlyParserProbe/1.0)"}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _jsonld_products(soup):
    products = []
    for node in soup.select('script[type="application/ld+json"]')[:30]:
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
                products.append({
                    "name": product.get("name"),
                    "brand": product.get("brand"),
                    "gtin13": product.get("gtin13"),
                    "gtin": product.get("gtin"),
                    "sku": product.get("sku"),
                    "offers": {k: offer.get(k) for k in ("price", "priceCurrency", "availability")} if isinstance(offer, dict) else None,
                })
    return products


def page_probe(url, adapter_name=None):
    result = {"url": url, "http_status": None, "title": None, "h1": None, "products": [], "adapter_result": None, "error": None}
    try:
        response = requests.get(url, headers=HEADERS, timeout=(4, 10), allow_redirects=True)
        result["http_status"] = response.status_code
        result["final_url"] = response.url
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        result["title"] = clean(soup.title.get_text(" ", strip=True)) if soup.title else None
        h1 = soup.find("h1")
        result["h1"] = clean(h1.get_text(" ", strip=True)) if h1 else None
        result["products"] = _jsonld_products(soup)
        if adapter_name:
            if adapter_name == "easycosmetic":
                # Parse the fetched HTML directly to isolate extraction from a
                # second network request, which can fail independently.
                parsed = easycosmetic._parse_product_html(response.url, response.text)
            else:
                module = deloox if adapter_name == "deloox" else parfumzentrum
                parsed = module.extract_product_page(
                    None, response.url, query=result["h1"] or QUERY, html=response.text
                )
            if parsed is None:
                result["adapter_result"] = {"status": "parser_returned_none"}
            elif adapter_name == "easycosmetic":
                result["adapter_result"] = {
                    "status": "parsed",
                    "name": parsed.get("name"),
                    "size_ml": parsed.get("size_ml"),
                    "price": parsed.get("price_num"),
                    "availability": parsed.get("availability"),
                    "available": parsed.get("available"),
                    "image": parsed.get("image"),
                    "brand": parsed.get("brand"),
                }
            elif adapter_name == "deloox":
                result["adapter_result"] = {
                    "status": "parsed",
                    "name": parsed.get("name"),
                    "size_ml": (parsed.get("attributes", {}).get("size_ml") or {}).get("value"),
                    "concentration": (parsed.get("attributes", {}).get("concentration") or {}).get("value"),
                    "price": (parsed.get("offer") or {}).get("price"),
                    "availability": (parsed.get("offer") or {}).get("availability"),
                    "gtin": ((parsed.get("identity") or {}).get("gtin") or {}).get("value"),
                }
            else:
                result["adapter_result"] = {
                    "status": "parsed",
                    "name": parsed.get("name"),
                    "size_ml": parsed.get("size_ml"),
                    "concentration": parsed.get("concentration"),
                    "price": parsed.get("price_num"),
                    "availability": parsed.get("availability"),
                    "gtin": parsed.get("gtin"),
                    "sku": parsed.get("sku"),
                }
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + clean(exc)[:240]
    return result


def adapter_probe(module):
    started = time.monotonic()
    contract = None
    try:
        stream = getattr(module, "search_stream", None)
        if callable(stream):
            contract = stream(QUERY)
            rows = contract.get("results", []) if isinstance(contract, dict) else []
        else:
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
        result = {
            "status": (contract.get("status") if isinstance(contract, dict) else None)
                      or ("results" if clean_rows else "zero_results"),
            "verified": contract.get("verified") if isinstance(contract, dict) else bool(clean_rows),
            "rows": clean_rows,
            "row_count": len(rows),
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
        if isinstance(contract, dict):
            result["error"] = contract.get("error")
            result["details"] = contract.get("details")
        return result
    except Exception as exc:
        return {"status": "error", "verified": False,
                "error": type(exc).__name__ + ": " + clean(exc)[:240],
                "elapsed_seconds": round(time.monotonic() - started, 2)}


def main():
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "scope": "Bounded public retailer HTTP and exact existing adapter calls using fetched HTML. No production database, catalog writes, or deployment.",
        "known_page_probes": {name: page_probe(url, adapter) for name, (url, adapter) in KNOWN_URLS.items()},
        "deloox_search": adapter_probe(deloox),
        "parfumzentrum_search": adapter_probe(parfumzentrum),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

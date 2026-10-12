#!/usr/bin/env python3
"""
ScentHunter — Easycosmetic selected-variant read-only diagnostic
===============================================================

Purpose:
Compare the base product URL and four known variant URLs using the REAL
Easycosmetic scraper parser, while independently recording the final redirect
URL and raw HTML evidence for title, JSON-LD Product/Offer, selected controls,
prices, volume strings, image, and variant IDs.

Safety:
- Does not import or initialize catalog_engine.
- Does not call search(), ProductMatcher, production API, or database code.
- Does not write to ScentHunter or Easycosmetic.
- Only performs HTTP GET requests to the five explicitly listed product URLs.
- Prints one JSON report to stdout.

Run from the repository's backend directory:
    python diagnose_easycosmetic_variants_readonly.py

Required dependencies are already used by the Easycosmetic scraper:
    requests, beautifulsoup4
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


URLS = [
    (
        "base",
        "https://www.easycosmetic.de/valentino/donna-born-in-roma/"
        "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx",
    ),
    (
        "variant_107764",
        "https://www.easycosmetic.de/valentino/donna-born-in-roma/"
        "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx"
        "?variant=107764",
    ),
    (
        "variant_78097",
        "https://www.easycosmetic.de/valentino/donna-born-in-roma/"
        "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx"
        "?variant=78097",
    ),
    (
        "variant_78098",
        "https://www.easycosmetic.de/valentino/donna-born-in-roma/"
        "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx"
        "?variant=78098",
    ),
    (
        "variant_78099",
        "https://www.easycosmetic.de/valentino/donna-born-in-roma/"
        "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx"
        "?variant=78099",
    ),
]

TIMEOUT = (8, 20)
MAX_CONTEXT = 700
MAX_HTML_BYTES = 0


def load_real_scraper():
    """Load the repository's real scraper module by file path, without app startup."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "scrapers" / "easycosmetic" / "scraper.py",
        here / "backend" / "scrapers" / "easycosmetic" / "scraper.py",
    ]
    scraper_path = next((p for p in candidates if p.is_file()), None)
    if scraper_path is None:
        raise FileNotFoundError(
            "Could not find scrapers/easycosmetic/scraper.py. "
            "Run this script from the backend directory."
        )
    spec = importlib.util.spec_from_file_location(
        "scenthunter_easycosmetic_scraper_readonly", scraper_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load scraper module at {scraper_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, str(scraper_path)


def clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def jsonld_records(soup: BeautifulSoup):
    records = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        for node in walk_json(payload):
            kind = node.get("@type")
            if kind == "Product" or (
                isinstance(kind, list) and "Product" in kind
            ):
                offers = node.get("offers")
                if isinstance(offers, dict):
                    offer_summary = {
                        "price": offers.get("price"),
                        "priceCurrency": offers.get("priceCurrency"),
                        "availability": offers.get("availability"),
                        "sku": offers.get("sku"),
                        "url": offers.get("url"),
                    }
                elif isinstance(offers, list):
                    offer_summary = [
                        {
                            "price": item.get("price"),
                            "priceCurrency": item.get("priceCurrency"),
                            "availability": item.get("availability"),
                            "sku": item.get("sku"),
                            "url": item.get("url"),
                        }
                        for item in offers if isinstance(item, dict)
                    ]
                else:
                    offer_summary = offers
                records.append({
                    "name": node.get("name"),
                    "sku": node.get("sku"),
                    "gtin": node.get("gtin"),
                    "mpn": node.get("mpn"),
                    "brand": node.get("brand"),
                    "description": clean(node.get("description"))[:500],
                    "image": node.get("image"),
                    "url": node.get("url"),
                    "offers": offer_summary,
                })
    return records


def context_hits(html: str, patterns: list[str], limit: int = 12):
    out = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, html, flags=re.I))
        for match in matches[:3]:
            start = max(0, match.start() - 220)
            end = min(len(html), match.end() + 350)
            out.append({
                "pattern": pattern,
                "offset": match.start(),
                "context": clean(html[start:end])[:MAX_CONTEXT],
            })
            if len(out) >= limit:
                return out
    return out


def selected_controls(soup: BeautifulSoup):
    selectors = [
        "option[selected]",
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        "[aria-selected=true]",
        "[aria-checked=true]",
        "[data-variant]",
        "[data-variant-id]",
        "[data-product-variant]",
    ]
    found = []
    seen = set()
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            continue
        for node in nodes[:100]:
            attrs = {}
            for key in (
                "value", "selected", "checked", "aria-label", "aria-selected",
                "aria-checked", "title", "data-value", "data-variant",
                "data-variant-id", "data-product-variant", "id", "name",
            ):
                if node.has_attr(key):
                    attrs[key] = node.get(key)
            item = {
                "selector": selector,
                "tag": node.name,
                "text": clean(node.get_text(" ", strip=True))[:250],
                "attrs": attrs,
            }
            signature = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                seen.add(signature)
                found.append(item)
            if len(found) >= 100:
                return found
    return found


def parse_one(session: requests.Session, scraper, label: str, url: str):
    started = time.monotonic()
    result = {
        "label": label,
        "requested_url": url,
        "requested_variant": parse_qs(urlparse(url).query).get("variant", [None])[0],
        "http": {},
        "raw_page": {},
        "real_parser": {},
        "errors": [],
    }
    try:
        response = session.get(
            url,
            headers=getattr(scraper, "HEADERS", {}),
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        html = response.text or ""
        result["http"] = {
            "status_code": response.status_code,
            "final_url": response.url,
            "redirect_history": [
                {"status_code": item.status_code, "url": item.url, "location": item.headers.get("Location")}
                for item in response.history
            ],
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(response.content),
            "elapsed_sec": round(response.elapsed.total_seconds(), 3),
        }
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = soup.find("title")
        og_image = soup.select_one('meta[property="og:image"]')
        selected_image = (
            og_image.get("content") if og_image else None
        )
        products = jsonld_records(soup)
        visible_text = clean(soup.get_text(" ", strip=True))

        result["raw_page"] = {
            "h1": clean(h1.get_text(" ", strip=True)) if h1 else None,
            "html_title": clean(title.get_text(" ", strip=True)) if title else None,
            "og_image": selected_image,
            "product_jsonld": products[:20],
            "selected_controls": selected_controls(soup),
            "variant_and_volume_evidence": context_hits(
                html,
                [
                    r"variant.{0,40}(?:107764|78097|78098|78099)",
                    r"(?:107764|78097|78098|78099).{0,40}variant",
                    r"(?:30|50|100)\s?ml",
                    r"priceCurrency",
                    r"\"price\"\s*:",
                    r"selectedVariant",
                    r"selected_variant",
                    r"variantId",
                    r"variant_id",
                    r"productVariants",
                    r"variant-selector",
                ],
                limit=45,
            ),
            "visible_volume_mentions": list(dict.fromkeys(
                re.findall(r"(?<!\d)(?:30|50|100)\s?ml\b", visible_text, flags=re.I)
            ))[:30],
        }

        try:
            parsed = scraper._parse_product_html(url, html)
            result["real_parser"] = parsed or {"result": None}
        except Exception as exc:
            result["errors"].append({
                "stage": "real_parser",
                "type": type(exc).__name__,
                "message": str(exc),
            })

        if response.status_code >= 400:
            result["errors"].append({
                "stage": "http",
                "type": "HTTPStatus",
                "message": f"HTTP {response.status_code}",
            })
    except Exception as exc:
        result["errors"].append({
            "stage": "request",
            "type": type(exc).__name__,
            "message": str(exc),
        })
    result["elapsed_total_sec"] = round(time.monotonic() - started, 3)
    return result


def main():
    scraper, scraper_path = load_real_scraper()
    session = requests.Session()
    report = {
        "diagnostic": "easycosmetic-variant-raw-html-vs-real-parser-read-only-v1",
        "read_only": True,
        "database_written": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "catalog_engine_imported": False,
        "scraper_path": scraper_path,
        "target": "Valentino Donna Born in Roma Coral Fantasy Eau de Parfum Spray",
        "requested_url_count": len(URLS),
        "results": [],
        "comparison": {},
    }
    try:
        for label, url in URLS:
            report["results"].append(parse_one(session, scraper, label, url))
    finally:
        session.close()

    comparison = {}
    for item in report["results"]:
        parser = item.get("real_parser") or {}
        comparison[item["label"]] = {
            "requested_variant": item.get("requested_variant"),
            "status_code": item.get("http", {}).get("status_code"),
            "final_url": item.get("http", {}).get("final_url"),
            "h1": item.get("raw_page", {}).get("h1"),
            "jsonld_products": [
                {
                    "name": p.get("name"),
                    "offers": p.get("offers"),
                    "image": p.get("image"),
                }
                for p in item.get("raw_page", {}).get("product_jsonld", [])
            ],
            "parser_name": parser.get("name") if isinstance(parser, dict) else None,
            "parser_size_ml": parser.get("size_ml") if isinstance(parser, dict) else None,
            "parser_price": parser.get("price") if isinstance(parser, dict) else None,
            "parser_image": parser.get("image") if isinstance(parser, dict) else None,
            "errors": item.get("errors", []),
        }
    report["comparison"] = comparison
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

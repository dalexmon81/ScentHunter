#!/usr/bin/env python3
"""
ScentHunter — Easycosmetic.be selected-variant read-only diagnostic v2

Purpose:
Compare the official Belgian Easycosmetic product page and candidate variant
URLs against raw HTML/JSON-LD and the repository's REAL Easycosmetic parser.

Safety:
- Does not import catalog_engine.
- Does not call ProductMatcher, production search, discovery, or persistence.
- Does not write to ScentHunter or Easycosmetic.
- Performs HTTP GET requests only for the five URLs below.
- Candidate IDs 78097/78098/78099 are hypotheses carried over from the German
  page. This diagnostic does NOT assume that they are valid Belgian IDs.

Run from the repository's backend directory:
    python diagnose_easycosmetic_variants_readonly.py
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
from fastapi import APIRouter

router = APIRouter()

BASE = (
    "https://www.easycosmetic.be/valentino/donna-born-in-roma/"
    "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx"
)
URLS = [
    ("be_base", BASE),
    ("be_variant_107764", BASE + "?variant=107764"),
    ("be_candidate_variant_78097", BASE + "?variant=78097"),
    ("be_candidate_variant_78098", BASE + "?variant=78098"),
    ("be_candidate_variant_78099", BASE + "?variant=78099"),
]
TIMEOUT = (8, 20)
MAX_CONTEXT = 700


def load_real_scraper():
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


def product_jsonld(soup: BeautifulSoup):
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
            if kind != "Product" and not (
                isinstance(kind, list) and "Product" in kind
            ):
                continue
            offers = node.get("offers")
            if isinstance(offers, dict):
                offers = {
                    k: offers.get(k)
                    for k in ("price", "priceCurrency", "availability", "sku", "url")
                }
            elif isinstance(offers, list):
                offers = [
                    {k: offer.get(k) for k in
                     ("price", "priceCurrency", "availability", "sku", "url")}
                    for offer in offers if isinstance(offer, dict)
                ]
            records.append({
                "name": node.get("name"),
                "sku": node.get("sku"),
                "gtin": node.get("gtin"),
                "mpn": node.get("mpn"),
                "brand": node.get("brand"),
                "description": clean(node.get("description"))[:400],
                "image": node.get("image"),
                "url": node.get("url"),
                "offers": offers,
            })
    return records


def context_hits(html: str):
    patterns = [
        r"variant.{0,40}(?:107764|78097|78098|78099)",
        r"(?:107764|78097|78098|78099).{0,40}variant",
        r"(?:10|30|50|100)\s?ml",
        r"priceCurrency",
        r'"price"\s*:',
        r"selectedVariant",
        r"selected_variant",
        r"variantId",
        r"variant_id",
        r"productVariants",
        r"variant-selector",
    ]
    out = []
    for pattern in patterns:
        for match in list(re.finditer(pattern, html, flags=re.I))[:3]:
            start = max(0, match.start() - 220)
            end = min(len(html), match.end() + 350)
            out.append({
                "pattern": pattern,
                "offset": match.start(),
                "context": clean(html[start:end])[:MAX_CONTEXT],
            })
            if len(out) >= 40:
                return out
    return out


def selected_controls(soup: BeautifulSoup):
    selectors = [
        "option[selected]", 'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]', "[aria-selected=true]",
        "[aria-checked=true]", "[data-variant]", "[data-variant-id]",
        "[data-product-variant]",
    ]
    found, seen = [], set()
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            continue
        for node in nodes[:80]:
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
                "text": clean(node.get_text(" ", strip=True))[:200],
                "attrs": attrs,
            }
            signature = json.dumps(item, sort_keys=True, ensure_ascii=False)
            if signature not in seen:
                seen.add(signature)
                found.append(item)
            if len(found) >= 80:
                return found
    return found


def parse_one(session, scraper, label, url):
    started = time.monotonic()
    requested_variant = parse_qs(urlparse(url).query).get("variant", [None])[0]
    item = {
        "label": label,
        "requested_url": url,
        "requested_variant": requested_variant,
        "http": {},
        "raw_page": {},
        "real_parser": None,
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
        item["http"] = {
            "status_code": response.status_code,
            "final_url": response.url,
            "final_variant": parse_qs(urlparse(response.url).query).get(
                "variant", [None]
            )[0],
            "redirect_history": [
                {
                    "status_code": hop.status_code,
                    "url": hop.url,
                    "location": hop.headers.get("Location"),
                }
                for hop in response.history
            ],
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(response.content),
            "elapsed_sec": round(response.elapsed.total_seconds(), 3),
        }
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = soup.find("title")
        og_image = soup.select_one('meta[property="og:image"]')
        visible = clean(soup.get_text(" ", strip=True))
        item["raw_page"] = {
            "h1": clean(h1.get_text(" ", strip=True)) if h1 else None,
            "html_title": clean(title.get_text(" ", strip=True)) if title else None,
            "og_image": og_image.get("content") if og_image else None,
            "product_jsonld": product_jsonld(soup)[:20],
            "selected_controls": selected_controls(soup),
            "volume_mentions": list(dict.fromkeys(
                re.findall(r"(?<!\d)(?:10|30|50|100)\s?ml\b", visible, flags=re.I)
            ))[:30],
            "variant_and_price_evidence": context_hits(html),
        }
        try:
            # Pass the originally requested URL to test the scraper's actual
            # variant-selection and Belgian-host validation behavior.
            parsed = scraper._parse_product_html(url, html)
            item["real_parser"] = parsed
        except Exception as exc:
            item["errors"].append({
                "stage": "real_parser",
                "type": type(exc).__name__,
                "message": str(exc),
            })
        if response.status_code >= 400:
            item["errors"].append({
                "stage": "http",
                "type": "HTTPStatus",
                "message": f"HTTP {response.status_code}",
            })
    except Exception as exc:
        item["errors"].append({
            "stage": "request",
            "type": type(exc).__name__,
            "message": str(exc),
        })
    item["elapsed_total_sec"] = round(time.monotonic() - started, 3)
    return item


def run_diagnostic():
    scraper, scraper_path = load_real_scraper()
    session = requests.Session()
    report = {
        "diagnostic": "easycosmetic-be-variant-raw-html-vs-real-parser-read-only-v2",
        "read_only": True,
        "database_written": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "catalog_engine_imported": False,
        "discovery_called": False,
        "store_resync_called": False,
        "scraper_path": scraper_path,
        "target": "Valentino Donna Born in Roma Coral Fantasy Eau de Parfum Spray",
        "market": "Belgium (.be) only",
        "candidate_variant_ids_are_verified": False,
        "requested_url_count": len(URLS),
        "results": [],
        "comparison": {},
    }
    try:
        for label, url in URLS:
            report["results"].append(parse_one(session, scraper, label, url))
    finally:
        session.close()

    for item in report["results"]:
        parsed = item.get("real_parser")
        if not isinstance(parsed, dict):
            parsed = {}
        report["comparison"][item["label"]] = {
            "requested_variant": item.get("requested_variant"),
            "status_code": item.get("http", {}).get("status_code"),
            "final_url": item.get("http", {}).get("final_url"),
            "final_variant": item.get("http", {}).get("final_variant"),
            "h1": item.get("raw_page", {}).get("h1"),
            "jsonld_products": [
                {"name": p.get("name"), "sku": p.get("sku"),
                 "gtin": p.get("gtin"), "offers": p.get("offers")}
                for p in item.get("raw_page", {}).get("product_jsonld", [])
            ],
            "parser_name": parsed.get("name"),
            "parser_size_ml": parsed.get("size_ml"),
            "parser_price": parsed.get("price"),
            "parser_availability": parsed.get("availability"),
            "parser_url": parsed.get("url"),
            "errors": item.get("errors", []),
        }
    return report


@router.get("/diagnose-easycosmetic-variants-read-only")
def diagnose_easycosmetic_variants_readonly_endpoint():
    """Run the Belgian-market variant comparison without catalog writes."""
    return run_diagnostic()


if __name__ == "__main__":
    print(json.dumps(run_diagnostic(), ensure_ascii=False, indent=2))

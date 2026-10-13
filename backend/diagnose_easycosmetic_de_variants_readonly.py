#!/usr/bin/env python3
"""ScentHunter — Easycosmetic.de variant diagnostic (read-only).

GET requests only. Does not call ProductMatcher, production search, discovery,
catalog hydration, resync, or persistence.
Can be run as a CLI script or exposed through the FastAPI router.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter

router = APIRouter()

BASE = (
    "https://www.easycosmetic.de/valentino/donna-born-in-roma/"
    "valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx"
)
URLS = [
    ("de_base", BASE),
    ("de_variant_78097_30ml", BASE + "?variant=78097"),
    ("de_variant_107764_10ml", BASE + "?variant=107764"),
    ("de_variant_78098_50ml", BASE + "?variant=78098"),
    ("de_variant_78099_100ml", BASE + "?variant=78099"),
]
TIMEOUT = (8, 20)


def load_real_scraper():
    here = Path(__file__).resolve().parent
    candidates = [
        here / "scrapers" / "easycosmetic" / "scraper.py",
        here / "backend" / "scrapers" / "easycosmetic" / "scraper.py",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError(
            "Parser non trovato: eseguire lo script dalla cartella backend."
        )
    spec = importlib.util.spec_from_file_location(
        "scenthunter_easycosmetic_de_readonly", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossibile caricare il parser: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, str(path)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def jsonld_products(soup):
    products = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                stack.extend(node.values())
                kind = node.get("@type")
                if kind == "Product" or (
                    isinstance(kind, list) and "Product" in kind
                ):
                    products.append({
                        "name": node.get("name"),
                        "sku": node.get("sku"),
                        "mpn": node.get("mpn"),
                        "gtin": node.get("gtin"),
                        "offers": node.get("offers"),
                    })
    return products[:20]


def evidence(html, soup):
    patterns = [
        r"Artikelnummer.{0,100}",
        r"(?:10|30|50|100)\s?ml",
        r"variant.{0,60}(?:78097|107764|78098|78099)",
        r"(?:78097|107764|78098|78099).{0,60}variant",
        r"selectedVariant",
        r"productVariants",
        r"variant-selector",
    ]
    found = []
    for pattern in patterns:
        for match in list(re.finditer(pattern, html, re.I))[:5]:
            found.append({
                "pattern": pattern,
                "context": clean(html[max(0, match.start()-180):
                                      min(len(html), match.end()+260)])[:500],
            })
            if len(found) >= 30:
                return found
    return found


def run_diagnostic():
    scraper, scraper_path = load_real_scraper()
    session = requests.Session()
    report = {
        "diagnostic": "easycosmetic-de-variant-raw-html-vs-real-parser-read-only-v1",
        "read_only": True,
        "database_written": False,
        "catalog_written": False,
        "product_matcher_called": False,
        "production_search_called": False,
        "discovery_called": False,
        "store_resync_called": False,
        "scraper_path": scraper_path,
        "market": "Germany (.de)",
        "results": [],
    }
    try:
        for label, url in URLS:
            started = time.monotonic()
            item = {
                "label": label,
                "requested_url": url,
                "requested_variant": parse_qs(urlparse(url).query).get(
                    "variant", [None]
                )[0],
            }
            try:
                response = session.get(
                    url,
                    headers=getattr(scraper, "HEADERS", {}),
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                html = response.text or ""
                soup = BeautifulSoup(html, "html.parser")
                h1 = soup.find("h1")
                item["http"] = {
                    "status_code": response.status_code,
                    "final_url": response.url,
                    "final_variant": parse_qs(urlparse(response.url).query).get(
                        "variant", [None]
                    )[0],
                    "bytes": len(response.content),
                    "elapsed_sec": round(response.elapsed.total_seconds(), 3),
                    "redirects": [
                        {"status_code": hop.status_code, "url": hop.url,
                         "location": hop.headers.get("Location")}
                        for hop in response.history
                    ],
                }
                visible = clean(soup.get_text(" ", strip=True))
                item["raw_page"] = {
                    "h1": clean(h1.get_text(" ", strip=True)) if h1 else None,
                    "jsonld_products": jsonld_products(soup),
                    "visible_size_mentions": list(dict.fromkeys(
                        re.findall(r"(?<!\d)(?:10|30|50|100)\s?ml\b",
                                   visible, re.I)
                    ))[:30],
                    "article_number_mentions": [
                        clean(m.group(0)) for m in list(re.finditer(
                            r"Artikelnummer.{0,100}", visible, re.I
                        ))[:10]
                    ],
                    "variant_evidence": evidence(html, soup),
                }
                try:
                    item["real_parser"] = scraper._parse_product_html(url, html)
                except Exception as exc:
                    item["parser_error"] = f"{type(exc).__name__}: {exc}"
                if response.status_code >= 400:
                    item["http_error"] = f"HTTP {response.status_code}"
            except Exception as exc:
                item["request_error"] = f"{type(exc).__name__}: {exc}"
            item["elapsed_total_sec"] = round(time.monotonic() - started, 3)
            report["results"].append(item)
    finally:
        session.close()

    report["summary"] = []
    for item in report["results"]:
        parsed = item.get("real_parser") or {}
        report["summary"].append({
            "variant": item.get("requested_variant"),
            "status": (item.get("http") or {}).get("status_code"),
            "final_url": (item.get("http") or {}).get("final_url"),
            "h1": (item.get("raw_page") or {}).get("h1"),
            "parser_size_ml": parsed.get("size_ml"),
            "parser_price": parsed.get("price"),
            "parser_sku": parsed.get("sku"),
            "parser_url": parsed.get("url"),
            "error": item.get("request_error") or item.get("parser_error")
                    or item.get("http_error"),
        })
    return report


@router.get("/diagnose-easycosmetic-de-variants-read-only")
def diagnose_easycosmetic_de_variants_readonly_endpoint():
    return run_diagnostic()


if __name__ == "__main__":
    print(json.dumps(run_diagnostic(), ensure_ascii=False, indent=2, default=str))

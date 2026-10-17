"""
ScentHunter — Sabina variant discovery diagnostic (read-only).

Scopo:
- Leggere una sola pagina prodotto Sabina, senza modifiche.
- Ispezionare HTML, JSON-LD, controlli di selezione, riferimenti a varianti,
  prezzi, disponibilità e identificativi.
- Confrontare i dati grezzi con il parser Sabina realmente presente nel progetto.

Sicurezza:
- Non importa catalog_engine.
- Non chiama ProductMatcher, ricerca di produzione, discovery o hydration.
- Non scrive database né file.
- Effettua una sola richiesta HTTP GET alla URL indicata.
- Non costruisce URL di varianti e non presume che una variante sia acquistabile.

Registrazione manuale in backend/main.py:
    from diagnose_sabina_variants_readonly import router as diagnose_sabina_variants_readonly_router
    app.include_router(diagnose_sabina_variants_readonly_router)

Dopo il deploy:
    /diagnose-sabina-variants-read-only
    /diagnose-sabina-variants-read-only?url=<URL-pagina>&q=<query>

Esempio URL predefinita:
https://www.sabina.com/it/profumi-di-donna/31434-born-in-roma-donna-extradose-eau-de-parfum-valentino.html
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter()

DEFAULT_PRODUCT_URL = (
    "https://www.sabina.com/it/profumi-di-donna/"
    "31434-born-in-roma-donna-extradose-eau-de-parfum-valentino.html"
)
TIMEOUT = (8, 28)
MAX_CONTEXTS = 50
MAX_CONTEXT_LENGTH = 900
MAX_HTML_BYTES_REPORTED = 800000
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,es-ES;q=0.8,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.sabina.com/it/",
}


def _clean(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit] if text else None


def _jsonld_records(soup: BeautifulSoup) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(node: Any, source_index: int) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child, source_index)
        elif isinstance(node, dict):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() in {"product", "productgroup", "offer", "aggregateoffer"} for t in types if t):
                offers = node.get("offers")
                if isinstance(offers, list):
                    offers_out = [
                        {
                            "type": offer.get("@type"),
                            "name": _clean(offer.get("name")),
                            "sku": _clean(offer.get("sku")),
                            "url": _clean(offer.get("url"), 1000),
                            "price": offer.get("price"),
                            "priceCurrency": offer.get("priceCurrency"),
                            "availability": offer.get("availability"),
                            "itemCondition": offer.get("itemCondition"),
                            "seller": _clean(offer.get("seller")),
                            "description": _clean(offer.get("description")),
                        }
                        for offer in offers[:100] if isinstance(offer, dict)
                    ]
                elif isinstance(offers, dict):
                    offers_out = [{
                        "type": offers.get("@type"),
                        "name": _clean(offers.get("name")),
                        "sku": _clean(offers.get("sku")),
                        "url": _clean(offers.get("url"), 1000),
                        "price": offers.get("price"),
                        "priceCurrency": offers.get("priceCurrency"),
                        "availability": offers.get("availability"),
                        "itemCondition": offers.get("itemCondition"),
                        "seller": _clean(offers.get("seller")),
                        "description": _clean(offers.get("description")),
                    }]
                else:
                    offers_out = []
                records.append({
                    "jsonld_index": source_index,
                    "type": types,
                    "name": _clean(node.get("name")),
                    "sku": _clean(node.get("sku")),
                    "gtin": _clean(node.get("gtin") or node.get("gtin13") or node.get("gtin14")),
                    "mpn": _clean(node.get("mpn")),
                    "productID": _clean(node.get("productID")),
                    "description": _clean(node.get("description"), 1000),
                    "url": _clean(node.get("url"), 1000),
                    "image": node.get("image"),
                    "isVariantOf": node.get("isVariantOf"),
                    "variesBy": node.get("variesBy"),
                    "hasVariant": node.get("hasVariant"),
                    "offers": offers_out,
                })
            for key, child in node.items():
                if key not in {"offers", "hasVariant"}:
                    visit(child, source_index)

    for index, script in enumerate(soup.select('script[type="application/ld+json"]')):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            visit(json.loads(raw), index)
        except Exception:
            records.append({
                "jsonld_index": index,
                "parse_error": True,
                "raw_excerpt": _clean(raw, 350),
            })
    return records[:100]


def _control_inventory(soup: BeautifulSoup) -> dict[str, Any]:
    selectors = [
        "select", "option", 'input[type="radio"]', 'input[type="checkbox"]',
        'input[type="hidden"]', "button", "[role=option]", "[role=radio]",
        "[aria-selected]", "[aria-checked]", "[data-variant]", "[data-variant-id]",
        "[data-product-attribute]", "[data-product-variant]", "[data-id-product-attribute]",
        "[class*=variant i]", "[id*=variant i]", "[class*=attribute i]",
    ]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            continue
        for node in nodes[:160]:
            attrs = {}
            for key, value in node.attrs.items():
                if key in {
                    "value", "name", "id", "class", "type", "checked", "selected",
                    "disabled", "aria-label", "aria-selected", "aria-checked", "title",
                    "data-value", "data-id", "data-product", "data-product-attribute",
                    "data-variant", "data-variant-id", "data-product-variant",
                    "data-id-product-attribute", "data-price", "data-quantity",
                    "data-stock", "data-available", "href",
                }:
                    attrs[key] = value[:300] if isinstance(value, str) else value
            item = {
                "selector": selector,
                "tag": node.name,
                "text": _clean(node.get_text(" ", strip=True), 250),
                "attrs": attrs,
            }
            signature = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
            if signature in seen:
                continue
            seen.add(signature)
            found.append(item)
            if len(found) >= 180:
                return {"count_captured": len(found), "items": found}
    return {"count_captured": len(found), "items": found}


def _embedded_evidence(html: str) -> list[dict[str, Any]]:
    patterns = [
        r"(?<!\d)(?:10|15|20|25|30|40|50|60|75|80|90|100|125|150|200)\s?ml\b",
        r"productVariants", r"variants", r"combinations", r"attributes", r"quantityAvailable",
        r"minimal_quantity", r"id_product_attribute", r"product_attribute", r"selectedCombination",
        r"selected_combination", r"variantId", r"variant_id", r"price_amount", r"regular_price",
        r"sale_price", r"availability", r"out of stock", r"agotado", r"sin stock",
        r"avisarme", r"avísame", r"fammi sapere", r"notificarme",
    ]
    output = []
    for pattern in patterns:
        for match in list(re.finditer(pattern, html, re.I))[:4]:
            start = max(0, match.start() - 240)
            end = min(len(html), match.end() + 500)
            output.append({
                "pattern": pattern,
                "offset": match.start(),
                "context": _clean(html[start:end], MAX_CONTEXT_LENGTH),
            })
            if len(output) >= MAX_CONTEXTS:
                return output
    return output


def _visible_summary(soup: BeautifulSoup) -> dict[str, Any]:
    text = _clean(soup.get_text(" ", strip=True), 16000) or ""
    volumes = re.findall(
        r"(?<!\d)(?:10|15|20|25|30|40|50|60|75|80|90|100|125|150|200)\s?ml\b",
        text, re.I,
    )
    h1 = soup.find("h1")
    title = soup.find("title")
    return {
        "h1": _clean(h1.get_text(" ", strip=True)) if h1 else None,
        "html_title": _clean(title.get_text(" ", strip=True)) if title else None,
        "visible_volume_mentions": list(dict.fromkeys(v.upper().replace(" ", "") for v in volumes))[:60],
        "visible_text_excerpt": text[:5000],
    }


def _run_real_parser(url: str, html: str, query: str) -> dict[str, Any]:
    try:
        from scrapers.sabina import scraper
        parser = getattr(scraper, "extract_product_page", None)
        if not callable(parser):
            return {"called": False, "reason": "extract_product_page_not_callable"}
        started = time.monotonic()
        try:
            parsed = parser(
                requests.Session(), url, query,
                authoritative_search=False, html=html,
            )
        except TypeError as exc:
            return {
                "called": False,
                "reason": "parser_signature_mismatch",
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            "called": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "result": parsed,
        }
    except Exception as exc:
        return {"called": False, "error": f"{type(exc).__name__}: {exc}"}


@router.get("/diagnose-sabina-variants-read-only")
def diagnose_sabina_variants_read_only(
    url: str = Query(DEFAULT_PRODUCT_URL, description="URL di una singola pagina prodotto Sabina"),
    q: str = Query("Born in Roma Extradose Donna", description="Query usata solo per il confronto col parser"),
):
    started = time.monotonic()
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or parsed_url.hostname not in {"www.sabina.com", "sabina.com"}:
        return {
            "diagnostic": "sabina-variants-read-only-v1",
            "ok": False,
            "error": "url_not_allowed",
            "allowed_hosts": ["www.sabina.com", "sabina.com"],
            "read_only": True,
            "http_requests_limit": 0,
        }

    report: dict[str, Any] = {
        "diagnostic": "sabina-variants-read-only-v1",
        "ok": False,
        "read_only": True,
        "database_written": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "catalog_engine_imported": False,
        "discovery_called": False,
        "hydration_called": False,
        "http_requests_limit": 1,
        "requested_url": url,
        "query": q,
        "http": {},
        "raw_page": {},
        "real_parser": None,
        "errors": [],
    }

    session = requests.Session()
    try:
        response = session.get(
            url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
        )
        html = response.text or ""
        report["http"] = {
            "status_code": response.status_code,
            "final_url": response.url,
            "redirect_history": [
                {
                    "status_code": hop.status_code,
                    "url": hop.url,
                    "location": hop.headers.get("Location"),
                } for hop in response.history
            ],
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(response.content),
            "bytes_reported_cap": MAX_HTML_BYTES_REPORTED,
            "elapsed_sec": round(response.elapsed.total_seconds(), 3),
        }
        soup = BeautifulSoup(html, "html.parser")
        report["raw_page"] = {
            **_visible_summary(soup),
            "jsonld_products_and_offers": _jsonld_records(soup),
            "controls": _control_inventory(soup),
            "embedded_variant_price_stock_evidence": _embedded_evidence(html),
        }
        report["real_parser"] = _run_real_parser(response.url, html, q)
        report["ok"] = 200 <= response.status_code < 400
        if response.status_code >= 400:
            report["errors"].append({
                "stage": "http",
                "type": "HTTPStatus",
                "message": f"HTTP {response.status_code}",
            })
    except Exception as exc:
        report["errors"].append({
            "stage": "request_or_parse",
            "type": type(exc).__name__,
            "message": str(exc),
        })
    finally:
        session.close()
    report["elapsed_total_sec"] = round(time.monotonic() - started, 3)
    return report

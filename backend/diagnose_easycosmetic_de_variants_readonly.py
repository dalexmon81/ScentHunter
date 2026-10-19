#!/usr/bin/env python3
"""ScentHunter — Easycosmetic.de diagnostics, read-only.

Preserves the existing variant and refresh-handoff endpoints. Adds a bounded
repeat-fetch comparison that fingerprints the raw response and independently
runs the exact parser handoff used by catalog_engine.refresh_url(), without
calling refresh_url or touching any database/queue.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
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
HANDOFF_URLS = [
    ("l_occitane_hand_cream",
     "https://www.easycosmetic.de/loccitane/karite/loccitane-karite-creme-mains.aspx"),
    ("madara_scalp_peel",
     "https://www.easycosmetic.de/madara/hair-care/madara-hair-care-scalp-peel-serum.aspx"),
]
REPEAT_URLS = HANDOFF_URLS
REPEAT_COUNT = 2
TIMEOUT = (8, 20)


def load_real_scraper():
    here = Path(__file__).resolve().parent
    candidates = [
        here / "scrapers" / "easycosmetic" / "scraper.py",
        here / "backend" / "scrapers" / "easycosmetic" / "scraper.py",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError("Parser non trovato: eseguire lo script dalla cartella backend.")
    spec = importlib.util.spec_from_file_location("scenthunter_easycosmetic_de_readonly", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossibile caricare il parser: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, str(path)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def safe_product_summary(value):
    if not isinstance(value, dict):
        return {"type": type(value).__name__ if value is not None else None,
                "is_dict": False, "name": None, "price": None,
                "price_num": None, "size_ml": None, "sku": None, "url": None,
                "accepted_by_refresh_url": False}
    name = value.get("name")
    return {
        "type": "dict", "is_dict": True,
        "name": name, "price": value.get("price"),
        "price_num": value.get("price_num"), "size_ml": value.get("size_ml"),
        "sku": value.get("sku"), "url": value.get("url"),
        "accepted_by_refresh_url": bool(name),
    }


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
                kind = node.get("@type")
                if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
                    products.append({k: node.get(k) for k in ("name", "sku", "mpn", "gtin")})
                stack.extend(node.values())
    return products[:20]


def evidence(html, soup):
    patterns = [
        r"Artikelnummer.{0,100}", r"(?:10|30|50|100)\s?ml",
        r"variant.{0,60}(?:78097|107764|78098|78099)",
        r"(?:78097|107764|78098|78099).{0,60}variant",
        r"selectedVariant", r"productVariants", r"variant-selector",
    ]
    found = []
    for pattern in patterns:
        for match in list(re.finditer(pattern, html, re.I))[:5]:
            found.append({"pattern": pattern,
                          "context": clean(html[max(0, match.start()-180):
                                                min(len(html), match.end()+260)])[:500]})
            if len(found) >= 30:
                return found
    return found


def run_variant_diagnostic():
    scraper, scraper_path = load_real_scraper()
    session = requests.Session()
    report = {
        "diagnostic": "easycosmetic-de-variant-raw-html-vs-real-parser-read-only-v3",
        "read_only": True, "database_written": False, "catalog_written": False,
        "product_matcher_called": False, "production_search_called": False,
        "discovery_called": False, "store_resync_called": False,
        "scraper_path": scraper_path, "market": "Germany (.de)", "results": [],
    }
    try:
        for label, url in URLS:
            started = time.monotonic()
            item = {"label": label, "requested_url": url,
                    "requested_variant": parse_qs(urlparse(url).query).get("variant", [None])[0]}
            try:
                response = session.get(url, headers=getattr(scraper, "HEADERS", {}),
                                       timeout=TIMEOUT, allow_redirects=True)
                html = response.text or ""
                soup = BeautifulSoup(html, "html.parser")
                h1 = soup.find("h1")
                item["http"] = {
                    "status_code": response.status_code, "final_url": response.url,
                    "final_variant": parse_qs(urlparse(response.url).query).get("variant", [None])[0],
                    "bytes": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "elapsed_sec": round(response.elapsed.total_seconds(), 3),
                    "redirects": [{"status_code": hop.status_code, "url": hop.url,
                                   "location": hop.headers.get("Location")} for hop in response.history],
                }
                visible = clean(soup.get_text(" ", strip=True))
                item["raw_page"] = {
                    "h1": clean(h1.get_text(" ", strip=True)) if h1 else None,
                    "jsonld_products": jsonld_products(soup),
                    "visible_size_mentions": list(dict.fromkeys(
                        re.findall(r"(?<!\d)(?:10|30|50|100)\s?ml\b", visible, re.I)))[:30],
                    "article_number_mentions": [clean(m.group(0)) for m in list(
                        re.finditer(r"Artikelnummer.{0,100}", visible, re.I))[:10]],
                    "variant_evidence": evidence(html, soup),
                }
                try:
                    item["real_parser"] = safe_product_summary(scraper._parse_product_html(url, html))
                except Exception as exc:
                    item["parser_error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
                if response.status_code >= 400:
                    item["http_error"] = f"HTTP {response.status_code}"
            except Exception as exc:
                item["request_error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
            item["elapsed_total_sec"] = round(time.monotonic() - started, 3)
            report["results"].append(item)
    finally:
        session.close()
    report["summary"] = [{
        "variant": x.get("requested_variant"),
        "status": (x.get("http") or {}).get("status_code"),
        "sha256": (x.get("http") or {}).get("sha256"),
        "final_url": (x.get("http") or {}).get("final_url"),
        "h1": (x.get("raw_page") or {}).get("h1"),
        "parser_size_ml": (x.get("real_parser") or {}).get("size_ml"),
        "parser_price": (x.get("real_parser") or {}).get("price"),
        "parser_sku": (x.get("real_parser") or {}).get("sku"),
        "error": x.get("request_error") or x.get("parser_error") or x.get("http_error"),
    } for x in report["results"]]
    return report


def _module_fingerprint(module):
    path = getattr(module, "__file__", None)
    result = {"module": getattr(module, "__name__", None), "path": path}
    try:
        raw = Path(path).read_bytes() if path else b""
        result["file_sha256"] = hashlib.sha256(raw).hexdigest() if raw else None
        result["file_bytes"] = len(raw) if raw else None
    except Exception as exc:
        result["fingerprint_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


def _parser_signature(parser_module):
    fn = getattr(parser_module, "extract_product_page", None)
    if not callable(fn):
        fn = getattr(parser_module, "_extract_product", None)
    if not callable(fn):
        return {"available": False, "name": None, "signature": None}
    try:
        signature = str(inspect.signature(fn))
    except Exception as exc:
        signature = f"<signature_error:{type(exc).__name__}:{str(exc)[:120]}>"
    return {"available": True, "name": getattr(fn, "__name__", None), "signature": signature}


def _run_one_handoff(engine, url, html_data, final_url):
    """Run both parsers separately; never invokes refresh_url or persistence."""
    out = {}
    retailer = getattr(engine, "_secondary_store_parser", None)
    generic = getattr(engine, "parse_product", None)
    try:
        value = retailer("easycosmetic", final_url, url, html_data=html_data) if callable(retailer) else None
        out["retailer_parser"] = safe_product_summary(value)
    except Exception as exc:
        out["retailer_parser"] = {"exception": f"{type(exc).__name__}: {str(exc)[:400]}",
                                  "accepted_by_refresh_url": False}
    try:
        value = generic("easycosmetic", final_url, html_data) if callable(generic) else None
        out["generic_parser"] = safe_product_summary(value)
        out["generic_parser"]["available"] = callable(generic)
    except Exception as exc:
        out["generic_parser"] = {"available": callable(generic),
                                 "exception": f"{type(exc).__name__}: {str(exc)[:400]}",
                                 "accepted_by_refresh_url": False}
    return out


def run_handoff_diagnostic():
    report = {
        "diagnostic": "easycosmetic-refresh-handoff-read-only-v3",
        "ok": True, "read_only": True, "database_writes": False,
        "refresh_url_called": False, "hydration_queue_touched": False,
        "production_search_called": False, "product_matcher_called": False,
        "repeat_fetch_count_per_url": REPEAT_COUNT, "targets": [],
    }
    try:
        engine = importlib.import_module("catalog_engine")
        http_get = getattr(engine, "http_get", None)
        retailer_parser = getattr(engine, "_secondary_store_parser", None)
        generic_parser = getattr(engine, "parse_product", None)
        if not callable(http_get) or not callable(retailer_parser):
            report.update(ok=False, error="required_catalog_engine_function_unavailable")
            return report
        report["catalog_engine"] = _module_fingerprint(engine)
        report["catalog_engine_functions"] = {
            "http_get": callable(http_get), "secondary_store_parser": callable(retailer_parser),
            "parse_product": callable(generic_parser),
        }
    except Exception as exc:
        report.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:400]}")
        return report

    try:
        scraper_module, scraper_path = load_real_scraper()
        report["easycosmetic_scraper"] = _module_fingerprint(scraper_module)
        report["easycosmetic_scraper"]["loaded_path"] = scraper_path
        report["easycosmetic_parser_signature"] = _parser_signature(scraper_module)
    except Exception as exc:
        report["easycosmetic_scraper_load_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"

    for label, url in REPEAT_URLS:
        target = {"label": label, "requested_url": url, "attempts": []}
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "www.easycosmetic.de":
            target["error"] = "url_not_allowed"
            report["targets"].append(target)
            continue
        for attempt_no in range(1, REPEAT_COUNT + 1):
            attempt = {"attempt": attempt_no}
            try:
                started = time.monotonic()
                status, final_url, html_data = http_get(url, timeout=18)
                raw = html_data if isinstance(html_data, bytes) else str(html_data or "").encode("utf-8", errors="replace")
                attempt["http"] = {
                    "status": status, "final_url": final_url,
                    "final_host": urlparse(final_url).hostname,
                    "html_type": type(html_data).__name__, "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "elapsed_total_sec": round(time.monotonic() - started, 3),
                    "utf8_replacement_decode_bytes": len(raw.decode("utf-8", errors="replace").encode("utf-8")),
                }
                final_host = urlparse(final_url).hostname
                if final_host not in {"easycosmetic.de", "www.easycosmetic.de"}:
                    attempt["error"] = "final_host_not_allowed"
                elif status >= 400:
                    attempt["error"] = f"http_status_{status}"
                else:
                    # Reproduce refresh_url's parser-selection condition without calling refresh_url.
                    module = importlib.import_module("scrapers.easycosmetic.scraper")
                    fn = getattr(module, "extract_product_page", None)
                    if not callable(fn):
                        fn = getattr(module, "_extract_product", None)
                    attempt["parser_available_as_refresh_url_checks"] = callable(fn)
                    if callable(fn):
                        try:
                            attempt["retailer_handoff"] = _run_one_handoff(engine, url, html_data, final_url)["retailer_parser"]
                        except Exception as exc:
                            attempt["retailer_handoff_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
                    # The same parser call is also performed with the loaded module used for signature/path evidence.
                    try:
                        retailer_result = retailer_parser("easycosmetic", final_url, url, html_data=html_data)
                        attempt["secondary_parser"] = safe_product_summary(retailer_result)
                    except Exception as exc:
                        attempt["secondary_parser"] = {"exception": f"{type(exc).__name__}: {str(exc)[:400]}",
                                                       "accepted_by_refresh_url": False}
                    try:
                        generic_result = generic_parser("easycosmetic", final_url, html_data) if callable(generic_parser) else None
                        attempt["generic_parser"] = safe_product_summary(generic_result)
                        attempt["generic_parser"]["available"] = callable(generic_parser)
                    except Exception as exc:
                        attempt["generic_parser"] = {"available": callable(generic_parser),
                                                     "exception": f"{type(exc).__name__}: {str(exc)[:400]}",
                                                     "accepted_by_refresh_url": False}
                    # Exact scraper parser with the UTF-8 replacement-decoded HTML used by the handoff.
                    try:
                        parser_fn = getattr(scraper_module, "extract_product_page", None)
                        if callable(parser_fn):
                            decoded = raw.decode("utf-8", errors="replace")
                            sig = inspect.signature(parser_fn)
                            kwargs = {"html": decoded} if "html" in sig.parameters else {}
                            with requests.Session() as session:
                                direct = parser_fn(session, url, urlparse(url).path.rsplit("/", 1)[-1], **kwargs)
                            attempt["direct_scraper_parser"] = safe_product_summary(direct)
                        else:
                            attempt["direct_scraper_parser"] = {"available": False}
                    except Exception as exc:
                        attempt["direct_scraper_parser"] = {"exception": f"{type(exc).__name__}: {str(exc)[:400]}",
                                                            "accepted_by_refresh_url": False}
                    retailer_ok = bool((attempt.get("secondary_parser") or {}).get("accepted_by_refresh_url"))
                    generic_ok = bool((attempt.get("generic_parser") or {}).get("accepted_by_refresh_url"))
                    attempt["interpretation"] = (
                        "retailer_failed_generic_succeeded" if not retailer_ok and generic_ok
                        else "both_parsers_failed" if not retailer_ok and not generic_ok
                        else "retailer_parser_succeeded"
                    )
            except Exception as exc:
                attempt["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            target["attempts"].append(attempt)
        hashes = [(a.get("http") or {}).get("sha256") for a in target["attempts"]]
        target["comparison"] = {
            "all_http_hashes_equal": len([h for h in hashes if h]) == REPEAT_COUNT and len(set(hashes)) == 1,
            "hashes": hashes,
            "parser_outcomes": [a.get("interpretation") for a in target["attempts"]],
        }
        report["targets"].append(target)
    return report


@router.get("/diagnose-easycosmetic-de-variants-read-only")
def diagnose_easycosmetic_de_variants_readonly_endpoint():
    return run_variant_diagnostic()


@router.get("/diagnose-easycosmetic-refresh-handoff-read-only")
def diagnose_easycosmetic_refresh_handoff_endpoint():
    return run_handoff_diagnostic()


if __name__ == "__main__":
    print(json.dumps({"variants": run_variant_diagnostic(),
                      "handoff": run_handoff_diagnostic()},
                     ensure_ascii=False, indent=2, default=str))

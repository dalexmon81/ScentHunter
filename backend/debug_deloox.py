from __future__ import annotations

import hashlib
import inspect
import json
import re
import sys
import time
import traceback
from collections import Counter
from types import ModuleType
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])

DLOOX_BASE = "https://www.deloox.be"
KNOWN_URLS = [
    "https://www.deloox.be/produit/1214441/valentino-born-in-roma-uomo-eau-de-toilette-100-ml.html",
    "https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html",
    "https://www.deloox.be/produit/1359237/valentino-born-in-roma-the-gold-uomo-eau-de-toilette-100-ml.html",
    "https://www.deloox.be/produit/1359240/valentino-born-in-roma-the-gold-donna-eau-de-parfum-100-ml.html",
]


def _short(value, limit=1200):
    try:
        if isinstance(value, str):
            return value[:limit]
        if isinstance(value, (list, tuple, set)):
            data = list(value)
            return {
                "type": type(value).__name__,
                "count": len(data),
                "items": [_short(x, 500) for x in data[:20]],
            }
        if isinstance(value, dict):
            return {
                "type": "dict",
                "keys": list(value.keys())[:80],
                "sample": {str(k): _short(v, 500) for k, v in list(value.items())[:20]},
            }
        return repr(value)[:limit]
    except Exception as exc:
        return f"<summary_error:{type(exc).__name__}:{exc}>"


def _source(obj):
    try:
        return inspect.getsource(obj)
    except Exception as exc:
        return f"<SOURCE_ERROR {type(exc).__name__}: {exc}>"


def _module_fingerprint(module: ModuleType):
    path = getattr(module, "__file__", None)
    origin = getattr(getattr(module, "__spec__", None), "origin", None)
    source = ""
    source_error = None

    if path:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            source = raw.decode("utf-8", errors="replace")
            sha = hashlib.sha256(raw).hexdigest()
            lines = source.count("\n") + 1
        except Exception as exc:
            sha = None
            lines = None
            source_error = f"{type(exc).__name__}: {exc}"
    else:
        sha = None
        lines = None
        source_error = "module_has_no___file__"

    return {
        "module_name": module.__name__,
        "module_file": path,
        "module_origin": origin,
        "module_source_sha256": sha,
        "module_source_lines": lines,
        "module_source_error": source_error,
        "module_source_text": source,
    }


def _module_functions(module):
    names = []
    for name in dir(module):
        try:
            value = getattr(module, name)
        except Exception:
            continue
        if callable(value) and (
            name == "discover"
            or name == "_discover"
            or "candidate" in name.lower()
            or "product" in name.lower()
            or "search" in name.lower()
            or "category" in name.lower()
            or "sitemap" in name.lower()
        ):
            names.append(name)
    return sorted(set(names))


def _is_deloox_product_url(url):
    try:
        p = urlparse(str(url))
        host = p.netloc.lower()
        path = p.path.lower()
        return (
            host in {"deloox.be", "www.deloox.be"}
            and re.search(r"/(?:produit|product|products?)/\d+/", path) is not None
        )
    except Exception:
        return False


def _generic_raw_urls(html, base_url):
    soup = BeautifulSoup(html or "", "html.parser")
    found = set()

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        u = urljoin(base_url, href).split("#", 1)[0].split("?", 1)[0]
        if _is_deloox_product_url(u):
            found.add(u)

    patterns = [
        r'https?://(?:www\.)?deloox\.be/[^"\'<>\s]+/(?:produit|product|products?)/\d+/[^"\'<>\s]+',
        r'["\']((?:/)?(?:en/|fr/|nl/|it/)?(?:produit|product|products?)/\d+/[^"\']+)["\']',
    ]

    for pattern in patterns:
        for raw in re.findall(pattern, html or "", re.I):
            u = urljoin(base_url, raw).split("#", 1)[0].split("?", 1)[0]
            if _is_deloox_product_url(u):
                found.add(u)

    return sorted(found)


def _born_urls(urls):
    out = []
    for u in urls:
        low = u.casefold()
        if "born-in-roma" in low or "born%20in%20roma" in low:
            out.append(u)
    return sorted(set(out))


def _jsonld_products(html):
    soup = BeautifulSoup(html or "", "html.parser")
    products = []

    for script in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            typ = item.get("@type")
            is_product = typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            )
            if is_product:
                products.append({
                    "name": item.get("name"),
                    "brand": item.get("brand"),
                    "sku": item.get("sku"),
                    "gtin": item.get("gtin13") or item.get("gtin"),
                    "url": item.get("url"),
                    "offers": _short(item.get("offers"), 1000),
                })

            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

    return products[:50]


class LoggedSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get(self, url, **kwargs):
        started = time.monotonic()
        try:
            response = super().get(url, **kwargs)
            self.calls.append({
                "url": str(url),
                "final_url": str(getattr(response, "url", "") or ""),
                "status": response.status_code,
                "bytes": len(response.content or b""),
                "content_type": response.headers.get("content-type"),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            })
            return response
        except Exception as exc:
            self.calls.append({
                "url": str(url),
                "status": None,
                "bytes": 0,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
            })
            raise


def _traceable_function_names(module, discover):
    wanted = set()

    try:
        for name in discover.__code__.co_names:
            value = getattr(module, name, None)
            if callable(value):
                wanted.add(name)
    except Exception:
        pass

    for name in (
        "_candidate_product_urls",
        "_candidate_contexts",
        "_discover_from_categories",
        "_category_product_line_links",
        "_sitemap_product_urls",
        "_find_catalog_filter_url",
        "_product",
        "product_url",
        "relevant",
        "matches",
    ):
        if callable(getattr(module, name, None)):
            wanted.add(name)

    return sorted(wanted)


def _profile_discover(module, discover, query, headers, timeout):
    """
    Runs the loaded discovery function in-memory only.

    The profiler records Python function entry/return values for functions
    belonging to the loaded Deloox module. This is deliberately read-only:
    no source file is edited and no production function is replaced.
    """
    events = []
    session = LoggedSession()
    if headers:
        session.headers.update(headers)

    function_names = set(_traceable_function_names(module, discover))
    previous_profile = sys.getprofile()

    started = time.monotonic()

    def profile(frame, event, arg):
        if event not in {"call", "return", "exception"}:
            return profile

        if frame.f_globals is not getattr(module, "__dict__", {}):
            return profile

        name = frame.f_code.co_name
        if name not in function_names and name not in {
            getattr(discover, "__name__", ""),
            "discover",
            "_discover",
        }:
            return profile

        if len(events) >= 300:
            return profile

        if event == "call":
            events.append({
                "event": "call",
                "function": name,
                "line": frame.f_lineno,
            })
        elif event == "return":
            events.append({
                "event": "return",
                "function": name,
                "line": frame.f_lineno,
                "value": _short(arg, 1600),
            })
        elif event == "exception":
            exc_type, exc_value, _tb = arg
            events.append({
                "event": "exception",
                "function": name,
                "line": frame.f_lineno,
                "exception": f"{getattr(exc_type, '__name__', str(exc_type))}: {exc_value}",
            })

        return profile

    # If the discovery function explicitly receives a Session, use our logged
    # session. If it creates its own Session, patch only the module's requests
    # object for the duration of this one diagnostic call.
    requests_obj = getattr(module, "requests", None)
    original_session_factory = getattr(requests_obj, "Session", None) if requests_obj else None

    try:
        if requests_obj is not None and original_session_factory is not None:
            requests_obj.Session = lambda: session

        sys.setprofile(profile)

        try:
            result = discover(session, query)
        except TypeError:
            # Some deployed variants expose discover(query) instead.
            result = discover(query)

        return {
            "ok": True,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "returned_type": type(result).__name__,
            "returned": _short(result, 8000),
            "returned_count": len(result) if isinstance(result, (list, tuple, set, dict)) else None,
            "profile_events": events,
            "http_calls": session.calls,
        }

    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "profile_events": events,
            "http_calls": session.calls,
        }

    finally:
        sys.setprofile(previous_profile)
        if requests_obj is not None and original_session_factory is not None:
            requests_obj.Session = original_session_factory
        session.close()


def _call_candidate_extractor(module, html, query):
    fn = getattr(module, "_candidate_product_urls", None)
    if not callable(fn):
        fn = getattr(module, "candidate_product_urls", None)

    if not callable(fn):
        return {
            "available": False,
            "reason": "candidate_extractor_not_found",
        }

    try:
        sig = inspect.signature(fn)
        kwargs = {}
        args = []

        params = list(sig.parameters.values())

        # Most deployed versions use:
        #   (html, query)
        # or:
        #   (html, query, discovery_query=None, accept_all_products=False)
        # Handle these without guessing beyond the signature.
        if len(params) >= 1:
            args.append(html)
        if len(params) >= 2:
            args.append(query)

        if "discovery_query" in sig.parameters:
            kwargs["discovery_query"] = query

        if "accept_all_products" in sig.parameters:
            kwargs["accept_all_products"] = True

        result = fn(*args, **kwargs)

        return {
            "available": True,
            "function": fn.__name__,
            "signature": str(sig),
            "returned_type": type(result).__name__,
            "returned_count": len(result) if isinstance(result, (list, tuple, set, dict)) else None,
            "returned": _short(result, 12000),
        }

    except Exception as exc:
        return {
            "available": True,
            "function": getattr(fn, "__name__", repr(fn)),
            "signature": str(inspect.signature(fn)),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _direct_pages(module, query):
    base = str(
        getattr(module, "BASE", None)
        or getattr(module, "BASE_URL", None)
        or DLOOX_BASE
    ).rstrip("/")

    headers = dict(getattr(module, "HEADERS", {}) or {})
    timeout = getattr(module, "TIMEOUT", (4, 8))

    pages = []
    session = requests.Session()
    if headers:
        session.headers.update(headers)

    for page_number in range(1, 5):
        candidates = [
            f"{base}/chercher.html?q={quote_plus(query)}&page={page_number}",
        ]

        if page_number == 1:
            candidates.append(f"{base}/chercher.html?q={quote_plus(query)}")

        report = {
            "page": page_number,
            "requested": candidates[0],
        }

        response = None
        try:
            for url in candidates:
                response = session.get(
                    url,
                    headers=headers or None,
                    timeout=timeout,
                    allow_redirects=True,
                )
                report["attempts"] = report.get("attempts", []) + [{
                    "url": url,
                    "status": response.status_code,
                    "final_url": response.url,
                    "bytes": len(response.content or b""),
                }]
                if response.status_code < 400 and response.text:
                    break

            if response is None:
                raise RuntimeError("no_response")

            html = response.text or ""
            raw_urls = _generic_raw_urls(html, response.url)
            born = _born_urls(raw_urls)

            report.update({
                "status": response.status_code,
                "final_url": response.url,
                "html_length": len(html),
                "generic_product_url_count": len(raw_urls),
                "born_in_roma_url_count": len(born),
                "born_in_roma_urls": born[:100],
                "candidate_extractor": _call_candidate_extractor(
                    module,
                    html,
                    query,
                ),
            })

        except Exception as exc:
            report.update({
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })

        pages.append(report)

    session.close()
    return pages


def _known_url_probe(module, query):
    headers = dict(getattr(module, "HEADERS", {}) or {})
    timeout = getattr(module, "TIMEOUT", (4, 8))

    rows = []
    session = requests.Session()
    if headers:
        session.headers.update(headers)

    for url in KNOWN_URLS:
        item = {
            "url": url,
            "is_generic_product_url": _is_deloox_product_url(url),
        }

        try:
            response = session.get(
                url,
                headers=headers or None,
                timeout=timeout,
                allow_redirects=True,
            )
            html = response.text or ""

            item.update({
                "status": response.status_code,
                "final_url": response.url,
                "bytes": len(response.content or b""),
                "html_length": len(html),
                "contains_born_in_roma": "born in roma" in html.casefold(),
                "contains_ivoory": "ivory" in html.casefold(),
                "jsonld_products": _jsonld_products(html),
            })

        except Exception as exc:
            item.update({
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })

    session.close()
    return rows


@router.get("/deloox-runtime-forensic")
def deloox_runtime_forensic(
    q: str = Query("Born in Roma", min_length=1),
):
    query = str(q or "").strip()
    started = time.monotonic()

    try:
        import importlib

        module = importlib.import_module("scrapers.deloox.scraper")

        fingerprint = _module_fingerprint(module)
        source_text = fingerprint.pop("module_source_text")

        public_functions = _module_functions(module)

        discover = getattr(module, "discover", None)
        discover_name = "discover"

        if not callable(discover):
            discover = getattr(module, "_discover", None)
            discover_name = "_discover"

        if not callable(discover):
            discover = None
            discover_name = None

        result = {
            "ok": True,
            "diagnostic": "DELOOX_RUNTIME_FORENSIC_V1",
            "query": query,
            "warning": "READ-ONLY DIAGNOSTIC. NO PRODUCTION FILE IS MODIFIED.",
            "runtime": fingerprint,
            "available_relevant_functions": public_functions,
            "discover": {
                "name": discover_name,
                "exists": callable(discover),
                "signature": str(inspect.signature(discover)) if callable(discover) else None,
                "source": _source(discover) if callable(discover) else None,
            },
            "helper_sources": {},
        }

        for name in public_functions:
            if name in {
                "discover",
                "_discover",
                "_candidate_product_urls",
                "_candidate_contexts",
                "_discover_from_categories",
                "_category_product_line_links",
                "_sitemap_product_urls",
                "_find_catalog_filter_url",
                "_product",
                "product_url",
                "relevant",
                "matches",
            }:
                value = getattr(module, name, None)
                if callable(value):
                    result["helper_sources"][name] = {
                        "signature": str(inspect.signature(value)),
                        "source": _source(value),
                    }

        result["direct_html"] = _direct_pages(module, query)
        result["known_product_pages"] = _known_url_probe(module, query)

        if callable(discover):
            headers = dict(getattr(module, "HEADERS", {}) or {})
            timeout = getattr(module, "TIMEOUT", (4, 8))
            result["discover_execution"] = _profile_discover(
                module,
                discover,
                query,
                headers,
                timeout,
            )
        else:
            result["discover_execution"] = {
                "ok": False,
                "error": "NO_DISCOVER_OR__DISCOVER_IN_LOADED_MODULE",
            }

        result["elapsed_total_ms"] = round((time.monotonic() - started) * 1000)

        return result

    except Exception as exc:
        return {
            "ok": False,
            "diagnostic": "DELOOX_RUNTIME_FORENSIC_V1",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "elapsed_total_ms": round((time.monotonic() - started) * 1000),
        }

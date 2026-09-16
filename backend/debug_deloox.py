from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing as mp
import re
import time
import traceback
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])

BASE_FALLBACK = "https://www.deloox.be"

KNOWN_URLS = [
    "https://www.deloox.be/produit/1214441/valentino-born-in-roma-uomo-eau-de-toilette-100-ml.html",
    "https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html",
    "https://www.deloox.be/produit/1359237/valentino-born-in-roma-the-gold-uomo-eau-de-toilette-100-ml.html",
    "https://www.deloox.be/produit/1359240/valentino-born-in-roma-the-gold-donna-eau-de-parfum-100-ml.html",
]


def _short(v, limit=2500):
    try:
        if isinstance(v, str):
            return v[:limit]
        if isinstance(v, (list, tuple, set)):
            x = list(v)
            return {"type": type(v).__name__, "count": len(x), "items": [_short(i, 700) for i in x[:30]]}
        if isinstance(v, dict):
            return {
                "type": "dict",
                "keys": list(v.keys())[:100],
                "sample": {str(k): _short(val, 700) for k, val in list(v.items())[:30]},
            }
        return repr(v)[:limit]
    except Exception as exc:
        return f"<summary_error:{type(exc).__name__}:{exc}>"


def _source(obj):
    if not callable(obj):
        return None
    try:
        return inspect.getsource(obj)
    except Exception as exc:
        return f"<SOURCE_ERROR {type(exc).__name__}: {exc}>"


def _fingerprint(module):
    path = getattr(module, "__file__", None)
    origin = getattr(getattr(module, "__spec__", None), "origin", None)

    try:
        raw = open(path, "rb").read() if path else b""
        text = raw.decode("utf-8", errors="replace")
        return {
            "module": module.__name__,
            "module_file": path,
            "module_origin": origin,
            "sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            "lines": text.count("\n") + 1 if text else None,
            "file_read_error": None,
        }
    except Exception as exc:
        return {
            "module": module.__name__,
            "module_file": path,
            "module_origin": origin,
            "sha256": None,
            "lines": None,
            "file_read_error": f"{type(exc).__name__}: {exc}",
        }


def _product_url(url):
    try:
        p = urlparse(str(url))
        return (
            p.netloc.lower() in {"deloox.be", "www.deloox.be"}
            and re.search(r"/(?:produit|product)/\d+/", p.path.lower()) is not None
        )
    except Exception:
        return False


def _raw_product_urls(html, final_url):
    soup = BeautifulSoup(html or "", "html.parser")
    out = set()

    for a in soup.find_all("a", href=True):
        u = urljoin(final_url, str(a.get("href") or "")).split("#", 1)[0].split("?", 1)[0]
        if _product_url(u):
            out.add(u)

    patterns = [
        r'https?://(?:www\.)?deloox\.be/[^"\'<>\s]+/(?:produit|product)/\d+/[^"\'<>\s]+',
        r'["\']((?:/)?(?:en/|fr/|nl/|it/)?(?:produit|product)/\d+/[^"\']+)["\']',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, html or "", re.I):
            u = urljoin(final_url, raw).split("#", 1)[0].split("?", 1)[0]
            if _product_url(u):
                out.add(u)

    return sorted(out)


def _born(urls):
    return sorted({u for u in urls if "born-in-roma" in u.casefold()})


def _http_probe(url, headers, timeout):
    t0 = time.monotonic()
    try:
        r = requests.get(
            url,
            headers=headers or None,
            timeout=timeout,
            allow_redirects=True,
        )
        return {
            "url": url,
            "status": r.status_code,
            "final_url": r.url,
            "bytes": len(r.content or b""),
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "born_url_count": len(_born(_raw_product_urls(r.text or "", r.url))),
            "born_urls": _born(_raw_product_urls(r.text or "", r.url))[:60],
            "html_length": len(r.text or ""),
        }
    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _child_discover(module_name, query, queue):
    started = time.monotonic()
    try:
        import importlib

        module = importlib.import_module(module_name)
        discover = getattr(module, "discover", None)
        name = "discover"

        if not callable(discover):
            discover = getattr(module, "_discover", None)
            name = "_discover"

        if not callable(discover):
            queue.put({
                "ok": False,
                "stage": "no_discover",
                "functions": sorted(
                    n for n in dir(module)
                    if n.startswith("_") and callable(getattr(module, n, None))
                )[:250],
            })
            return

        session = requests.Session()
        headers = dict(getattr(module, "HEADERS", {}) or {})
        timeout = getattr(module, "TIMEOUT", (2.0, 5.0))
        if headers:
            session.headers.update(headers)

        try:
            # Trace only functions belonging to the loaded Deloox module.
            wanted = set()
            try:
                wanted.update(n for n in discover.__code__.co_names if callable(getattr(module, n, None)))
            except Exception:
                pass

            for n in (
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
                if callable(getattr(module, n, None)):
                    wanted.add(n)

            events = []
            old_profile = __import__("sys").getprofile()

            def profile(frame, event, arg):
                if event not in ("call", "return", "exception"):
                    return profile
                if frame.f_globals is not module.__dict__:
                    return profile
                fn = frame.f_code.co_name
                if fn not in wanted and fn not in {name, "discover", "_discover"}:
                    return profile
                if len(events) >= 250:
                    return profile

                if event == "call":
                    events.append({"event": "call", "fn": fn, "line": frame.f_lineno})
                elif event == "return":
                    events.append({"event": "return", "fn": fn, "line": frame.f_lineno, "value": _short(arg, 1800)})
                else:
                    et, ev, _ = arg
                    events.append({
                        "event": "exception",
                        "fn": fn,
                        "line": frame.f_lineno,
                        "error": f"{getattr(et, '__name__', str(et))}: {ev}",
                    })
                return profile

            import sys
            sys.setprofile(profile)
            try:
                try:
                    result = discover(session, query)
                except TypeError:
                    result = discover(query)
            finally:
                sys.setprofile(old_profile)

            queue.put({
                "ok": True,
                "discover_name": name,
                "signature": str(inspect.signature(discover)),
                "source": _source(discover),
                "returned_type": type(result).__name__,
                "returned_count": len(result) if isinstance(result, (list, tuple, set, dict)) else None,
                "returned": _short(result, 15000),
                "profile_events": events,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            })
        finally:
            session.close()

    except Exception as exc:
        queue.put({
            "ok": False,
            "stage": "discover_execution",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        })


@router.get("/deloox-runtime-forensic")
def deloox_runtime_forensic(
    q: str = Query("Born in Roma", min_length=1),
    timeout_seconds: int = Query(20, ge=5, le=60),
):
    started = time.monotonic()
    query = str(q or "").strip()

    try:
        import importlib

        module = importlib.import_module("scrapers.deloox.scraper")
        fp = _fingerprint(module)

        discover = getattr(module, "discover", None)
        discover_name = "discover"
        if not callable(discover):
            discover = getattr(module, "_discover", None)
            discover_name = "_discover"

        helper_names = [
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
        ]

        helpers = {}
        for name in helper_names:
            fn = getattr(module, name, None)
            if callable(fn):
                helpers[name] = {
                    "signature": str(inspect.signature(fn)),
                    "source": _source(fn),
                }

        base = str(
            getattr(module, "BASE", None)
            or getattr(module, "BASE_URL", None)
            or BASE_FALLBACK
        ).rstrip("/")
        headers = dict(getattr(module, "HEADERS", {}) or {})
        timeout = getattr(module, "TIMEOUT", (2.0, 5.0))

        # Only ONE search page + the four known product pages here.
        # The discovery call itself is isolated in a killable subprocess.
        search_url = f"{base}/chercher.html?q={quote_plus(query)}"
        raw_search = _http_probe(search_url, headers, timeout)

        known = [_http_probe(u, headers, timeout) for u in KNOWN_URLS]

        queue = mp.Queue()
        proc = mp.Process(
            target=_child_discover,
            args=("scrapers.deloox.scraper", query, queue),
            daemon=True,
        )

        proc_started = time.monotonic()
        proc.start()
        proc.join(timeout_seconds)

        if proc.is_alive():
            proc.terminate()
            proc.join(3)
            discovery = {
                "ok": False,
                "timeout": True,
                "timeout_seconds": timeout_seconds,
                "error": f"discover_process_exceeded_{timeout_seconds}_seconds",
                "child_exitcode": proc.exitcode,
                "elapsed_ms": round((time.monotonic() - proc_started) * 1000),
            }
        else:
            try:
                discovery = queue.get_nowait()
            except Exception:
                discovery = {
                    "ok": False,
                    "error": "discover_process_finished_without_result",
                    "child_exitcode": proc.exitcode,
                    "elapsed_ms": round((time.monotonic() - proc_started) * 1000),
                }

        return {
            "ok": True,
            "diagnostic": "DELOOX_RUNTIME_FORENSIC_V2",
            "read_only": True,
            "query": query,
            "runtime": fp,
            "base_url": base,
            "configured_timeout": repr(timeout),
            "helpers": helpers,
            "raw_search_page": raw_search,
            "known_product_pages": known,
            "discover_execution": discovery,
            "total_elapsed_ms": round((time.monotonic() - started) * 1000),
        }

    except Exception as exc:
        return {
            "ok": False,
            "diagnostic": "DELOOX_RUNTIME_FORENSIC_V2",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "total_elapsed_ms": round((time.monotonic() - started) * 1000),
        }

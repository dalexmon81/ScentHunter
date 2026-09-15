"""
Temporary Sabina diagnostic router for ScentHunter.

Purpose:
- diagnose why a Sabina product such as Hawas Kobra is missing;
- show first-party search routes and every URL extracted from them;
- show whether Kobra/London/Ice are present in raw HTML even when the
  production link extractor does not select them;
- test external-search discovery separately, without changing production
  scraper behavior;
- trace exact product URLs through the real production product parser;
- inspect the Sabina RASASI category page as an independent discovery source.

This file does NOT modify the production Sabina scraper.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus

import requests
from fastapi import APIRouter, Query

# ScentHunter has used both package layouts depending on how Uvicorn is
# started. Keep the diagnostic import robust so a deployment does not fail
# merely because the application root is /app rather than its parent.
try:
    from backend.scrapers.sabina import scraper as sabina
except ModuleNotFoundError:
    from scrapers.sabina import scraper as sabina


router = APIRouter()
DIAG_TIMEOUT = getattr(sabina, "TIMEOUT", (3.0, 8.0))


KOBRA_URLS = [
    "https://www.sabina.com/it/profumi-da-uomo/56286-kobra-for-him-eau-de-parfum-rasasi.html",
    "https://www.sabina.com/fr/parfums-pour-homme/56286-kobra-for-him-eau-de-parfum-rasasi.html",
    "https://www.sabina.com/es/perfumes-hombre/56286-kobra-for-him-eau-de-parfum-rasasi.html",
]

LONDON_URLS = [
    "https://www.sabina.com/it/profumi-da-uomo/58822-hawas-london-eau-de-parfum-rasasi.html",
    "https://www.sabina.com/es/perfumes-hombre/58822-hawas-london-eau-de-parfum-rasasi.html",
]

ICE_URLS = [
    "https://www.sabina.com/en/mens-perfumes/39471-rasasi-hawas-ice-for-men-eau-de-parfum.html",
    "https://www.sabina.com/es/perfumes-hombre/39471-rasasi-hawas-ice-for-men-eau-de-parfum.html",
]


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _make_session():
    session = requests.Session()
    session.headers.update(sabina.HEADERS)
    return session


def _fetch(session, url):
    try:
        response = sabina._get(session, url)
        if response is None:
            return {
                "url": url,
                "status": None,
                "final_url": url,
                "html_length": 0,
                "text": "",
                "error": "sabina._get returned None",
            }
        try:
            text = response.text or ""
            return {
                "url": url,
                "status": response.status_code,
                "final_url": response.url,
                "html_length": len(text),
                "text": text,
            }
        finally:
            response.close()
    except Exception as exc:
        return {
            "url": url,
            "status": "EXCEPTION",
            "final_url": url,
            "html_length": 0,
            "text": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _snippet(text, needle, radius=350):
    low = text.casefold()
    pos = low.find(needle.casefold())
    if pos < 0:
        return None
    start = max(0, pos - radius)
    end = min(len(text), pos + len(needle) + radius)
    compact = re.sub(r"\s+", " ", text[start:end]).strip()
    return compact[:900]


def _raw_presence(text):
    low = text.casefold()
    return {
        "hawas": "hawas" in low,
        "kobra": "kobra" in low,
        "london": "london" in low,
        "hawas_ice": "hawas-ice" in low or "hawas ice" in low,
        "kobra_url_fragment": "56286" in low or "kobra-for-him" in low,
    }


def _extract_links(text, query):
    try:
        links = sabina._extract_product_links_from_html(text, query)
        return {
            "count": len(links),
            "links": links,
            "error": None,
        }
    except Exception as exc:
        return {
            "count": 0,
            "links": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _product_page_trace(session, url, query):
    """Run the real production product parser and expose its output."""
    try:
        rows = sabina._extract_product_page(url, query)
    except Exception as exc:
        return {
            "url": url,
            "status": "EXCEPTION",
            "error": f"{type(exc).__name__}: {exc}",
            "rows": [],
        }

    compact = []
    for row in rows:
        provenance = row.get("provenance")
        compact.append(
            {
                "name": row.get("name"),
                "brand": row.get("brand"),
                "price": row.get("price"),
                "price_num": row.get("price_num"),
                "currency": row.get("currency"),
                "size_ml": row.get("size_ml"),
                "concentration": row.get("concentration"),
                "availability": row.get("availability"),
                "price_source": (
                    provenance.get("price")
                    if isinstance(provenance, dict)
                    else None
                ),
                "url": row.get("url"),
                "sku": row.get("sku"),
                "store_product_id": row.get("store_product_id"),
                "image": row.get("image") or row.get("image_url"),
                "provenance": provenance,
            }
        )

    return {
        "url": url,
        "status": "OK",
        "row_count": len(compact),
        "rows": compact,
    }


def _trace_urls(session, urls, query):
    result = []
    seen = set()
    for url in urls:
        key = _norm(url)
        if key in seen:
            continue
        seen.add(key)
        result.append(_product_page_trace(session, url, query))
    return result


def _route_diagnostic(session, route, query):
    fetched = _fetch(session, route)
    text = fetched.pop("text", "")
    extracted = _extract_links(text, query) if text else {
        "count": 0,
        "links": [],
        "error": None,
    }
    presence = _raw_presence(text)
    return {
        **fetched,
        "extracted": extracted,
        "raw_presence": presence,
        "snippets": {
            "kobra": _snippet(text, "kobra"),
            "london": _snippet(text, "london"),
            "hawas ice": _snippet(text, "hawas ice"),
        },
    }


@router.get("/diagnose-sabina")
def diagnose_sabina(
    q: str = Query("Hawas", min_length=1, max_length=80),
):
    query = sabina._clean(q)
    q_encoded = quote_plus(query)
    session = _make_session()

    try:
        # Warmup only; this does not change production behavior.
        warmup = _fetch(session, sabina.BASE + "/it/")

        routes = [
            sabina.BASE + "/it/buscar?s=" + q_encoded,
            sabina.BASE + "/it/buscar?controller=search&s=" + q_encoded,
            sabina.BASE + "/it/buscar_old?s=" + q_encoded,
            sabina.BASE + "/it/buscar?search_query=" + q_encoded,
            sabina.BASE + "/it/buscar_old?search_query=" + q_encoded,
            sabina.BASE + "/it/search?s=" + q_encoded,
            sabina.BASE + "/es/buscar?s=" + q_encoded,
            sabina.BASE + "/es/buscar?controller=search&s=" + q_encoded,
            sabina.BASE + "/es/buscar_old?s=" + q_encoded,
            sabina.BASE + "/es/search?s=" + q_encoded,
        ]

        first_party_routes = [
            _route_diagnostic(session, route, query)
            for route in routes
        ]

        # Exact production first-party discovery.
        try:
            production_candidates = sabina._discover_from_first_party(
                session,
                query,
            )
            production_discovery_error = None
        except Exception as exc:
            production_candidates = []
            production_discovery_error = (
                f"{type(exc).__name__}: {exc}"
            )

        # External search is diagnostic only. We do not use its result to
        # alter production output here.
        try:
            external_candidates = sabina._discover_from_external_search(
                session,
                query,
            )
            external_discovery_error = None
        except Exception as exc:
            external_candidates = []
            external_discovery_error = (
                f"{type(exc).__name__}: {exc}"
            )

        # Independent category discovery: Sabina's RASASI page visibly
        # contains Kobra, so this tells us whether the product can be found
        # through a public first-party category even when search cannot.
        category_urls = [
            sabina.BASE + "/it/631_rasasi",
            sabina.BASE + "/es/631_rasasi",
        ]
        category_results = []
        category_links = []
        for url in category_urls:
            item = _fetch(session, url)
            text = item.pop("text", "")
            category_results.append(
                {
                    **item,
                    "raw_presence": _raw_presence(text),
                    "kobra_snippet": _snippet(text, "kobra"),
                    "london_snippet": _snippet(text, "london"),
                    "extracted_hawas_links": _extract_links(text, query),
                }
            )
            if text:
                try:
                    links = sabina._extract_product_links_from_html(
                        text,
                        query,
                    )
                    category_links.extend(links)
                except Exception:
                    pass

        # Exact targets, independent of discovery.
        exact_targets = {
            "kobra": KOBRA_URLS,
            "london": LONDON_URLS,
            "ice": ICE_URLS,
        }
        exact_traces = {
            key: _trace_urls(session, urls, query)
            for key, urls in exact_targets.items()
        }

        # Trace production candidates and external candidates separately.
        production_traces = [
            _product_page_trace(session, url, query)
            for url in production_candidates
        ]
        external_traces = [
            _product_page_trace(session, url, query)
            for url in external_candidates
        ]

        return {
            "query": query,
            "summary": {
                "max_candidates": getattr(sabina, "MAX_CANDIDATES", None),
                "production_discovery_count": len(production_candidates),
                "production_candidates": production_candidates,
                "external_discovery_count": len(external_candidates),
                "external_candidates": external_candidates,
                "category_hawas_link_count": len(category_links),
                "category_hawas_links": category_links,
            },
            "warmup": {
                key: value
                for key, value in warmup.items()
                if key != "text"
            },
            "production_discovery_error": production_discovery_error,
            "external_discovery_error": external_discovery_error,
            "first_party_routes": first_party_routes,
            "category_results": category_results,
            "production_candidate_traces": production_traces,
            "external_candidate_traces": external_traces,
            "exact_product_traces": exact_traces,
        }
    finally:
        session.close()

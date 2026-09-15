"""
Temporary Sabina diagnostic router for ScentHunter.

Purpose:
- inspect first-party discovery for a query;
- show every discovered candidate URL before product parsing;
- inspect each candidate's extracted title/price/price source;
- specifically trace Hawas Ice, London and Kobra.

No production scraper behavior is changed by this file.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

from backend.scrapers.sabina import scraper as sabina


router = APIRouter()

DIAG_TIMEOUT = getattr(sabina, "TIMEOUT", (3.0, 8.0))


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _fetch_raw(url):
    session = requests.Session()
    session.headers.update(sabina.HEADERS)
    try:
        response = session.get(
            url,
            timeout=DIAG_TIMEOUT,
            allow_redirects=True,
        )
        status = response.status_code
        final_url = response.url
        text = response.text
        response.close()
        return {
            "status": status,
            "final_url": final_url,
            "length": len(text),
            "text": text,
        }
    except Exception as exc:
        return {
            "status": None,
            "final_url": url,
            "length": 0,
            "text": "",
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        session.close()


def _product_page_trace(url, query):
    """Run the existing production extractor and expose its real output."""
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
        compact.append(
            {
                "name": row.get("name"),
                "brand": row.get("brand"),
                "price": row.get("price"),
                "price_num": row.get("price_num"),
                "size_ml": row.get("size_ml"),
                "concentration": row.get("concentration"),
                "availability": row.get("availability"),
                "price_source": (
                    row.get("provenance", {}).get("price")
                    if isinstance(row.get("provenance"), dict)
                    else None
                ),
                "url": row.get("url"),
                "sku": row.get("sku"),
                "store_product_id": row.get("store_product_id"),
            }
        )

    return {
        "url": url,
        "status": "OK",
        "row_count": len(compact),
        "rows": compact,
    }


@router.get("/diagnose-sabina")
def diagnose_sabina(
    q: str = Query("Hawas", min_length=1, max_length=80),
):
    query = sabina._clean(q)

    session = requests.Session()
    session.headers.update(sabina.HEADERS)

    first_party = []
    candidate_urls = []
    discovery_error = None

    try:
        try:
            response = sabina._get(
                session,
                sabina.BASE + "/it/",
            )
            if response is not None:
                response.close()
        except Exception as exc:
            discovery_error = (
                f"warmup {type(exc).__name__}: {exc}"
            )

        try:
            candidate_urls = sabina._discover_from_first_party(
                session,
                query,
            )
        except Exception as exc:
            discovery_error = (
                f"discovery {type(exc).__name__}: {exc}"
            )

        # Re-run each known first-party route directly so we can see
        # which route actually produced the candidates.
        q_encoded = quote_plus(query)
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

        for route in routes:
            try:
                response = sabina._get(session, route)
                if response is None:
                    first_party.append(
                        {
                            "url": route,
                            "status": None,
                            "candidate_count": 0,
                            "candidates": [],
                        }
                    )
                    continue

                try:
                    links = sabina._extract_product_links_from_html(
                        response.text,
                        query,
                    )
                    first_party.append(
                        {
                            "url": route,
                            "status": response.status_code,
                            "final_url": response.url,
                            "html_length": len(response.text),
                            "candidate_count": len(links),
                            "candidates": links,
                            "contains_hawas": (
                                "hawas" in response.text.casefold()
                            ),
                            "contains_kobra": (
                                "kobra" in response.text.casefold()
                            ),
                            "contains_london": (
                                "london" in response.text.casefold()
                            ),
                            "contains_ice": (
                                "hawas-ice" in response.text.casefold()
                                or "hawas ice" in response.text.casefold()
                            ),
                        }
                    )
                finally:
                    response.close()
            except Exception as exc:
                first_party.append(
                    {
                        "url": route,
                        "status": "EXCEPTION",
                        "error": f"{type(exc).__name__}: {exc}",
                        "candidate_count": 0,
                        "candidates": [],
                    }
                )

    finally:
        session.close()

    # Inspect every candidate through the exact production product parser.
    traces = [
        _product_page_trace(url, query)
        for url in candidate_urls
    ]

    target_traces = []
    for url in candidate_urls:
        low = _norm(url)
        if any(
            token in low
            for token in (
                "kobra",
                "london",
                "hawas-ice",
                "hawas_ice",
            )
        ):
            target_traces.append(
                _product_page_trace(url, query)
            )

    # If Ice was not discovered, try known product URL patterns from the
    # public Sabina catalog/search result without changing production code.
    known_targets = {
        "kobra": "https://www.sabina.com/fr/parfums-pour-homme/56286-kobra-for-him-eau-de-parfum-rasasi.html",
        "london": "https://www.sabina.com/fr/parfums-pour-femme/58822-hawas-london-eau-de-parfum-rasasi.html",
        "ice": "https://www.sabina.com/en/mens-perfumes/39471-rasasi-hawas-ice-for-men-eau-de-parfum.html",
    }

    known_product_traces = {
        key: _product_page_trace(url, query)
        for key, url in known_targets.items()
    }

    return {
        "query": query,
        "summary": {
            "max_candidates": getattr(
                sabina,
                "MAX_CANDIDATES",
                None,
            ),
            "production_discovery_count": len(candidate_urls),
            "production_candidates": candidate_urls,
            "production_trace_count": sum(
                item.get("row_count", 0)
                for item in traces
            ),
        },
        "discovery_error": discovery_error,
        "first_party_routes": first_party,
        "candidate_product_traces": traces,
        "target_product_traces": target_traces,
        "known_product_traces": known_product_traces,
    }

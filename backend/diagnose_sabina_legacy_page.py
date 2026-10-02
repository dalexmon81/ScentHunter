from __future__ import annotations

"""
ScentHunter - read-only Sabina single-page legacy discovery diagnostic.

Purpose:
    Isolate the exact hand-off between Sabina's native legacy search HTML and
    catalog_engine's generic Sabina URL extraction.

This endpoint:
    - fetches ONE known Sabina search page;
    - does not run production search;
    - does not run catalog discovery;
    - does not run ProductMatcher;
    - does not write the catalog or database;
    - does not start a resync;
    - calls only read-only parsing helpers from catalog_engine.

Endpoint:
    /diagnose-sabina-legacy-page?q=Liquid%20Brun
"""

import re
import time
import urllib.parse
from typing import Any

from fastapi import APIRouter, Query
from bs4 import BeautifulSoup

router = APIRouter()

DEFAULT_SEARCH_URL = (
    "https://www.sabina.com/it/ricerca_old?search_query=Liquid+Brun"
)
TARGET_PRODUCT_ID = "41708"
TARGET_PRODUCT_URL = (
    "https://www.sabina.com/it/profumi-di-donna/41708-"
    "liquid-brun-limited-edition-extrait-de-parfum.html"
)


def _load_engine():
    import catalog_engine as ce
    return ce


def _contains_exact_product_url(value: str) -> bool:
    if not value:
        return False
    decoded = urllib.parse.unquote(str(value))
    return TARGET_PRODUCT_URL.casefold() in decoded.casefold()


def _matching_hrefs(html: bytes | str, page_base: str) -> list[dict[str, Any]]:
    raw = html.decode("utf-8", "ignore") if isinstance(html, (bytes, bytearray)) else str(html)
    soup = BeautifulSoup(raw, "html.parser")
    out = []
    seen = set()

    for node in soup.find_all("a", href=True):
        href = str(node.get("href") or "")
        absolute = urllib.parse.urljoin(page_base, href).split("#", 1)[0]
        haystack = urllib.parse.unquote(absolute)
        if TARGET_PRODUCT_ID not in haystack and not _contains_exact_product_url(absolute):
            continue
        key = absolute
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "href": href,
                "absolute": absolute,
                "text": node.get_text(" ", strip=True)[:500],
            }
        )
    return out[:50]


def _hidden_id_evidence(html: bytes | str) -> list[dict[str, Any]]:
    raw = html.decode("utf-8", "ignore") if isinstance(html, (bytes, bytearray)) else str(html)
    soup = BeautifulSoup(raw, "html.parser")
    out = []
    for node in soup.find_all(
        attrs={"id": re.compile(r"^af_controller_product_ids$", re.I)}
    ):
        out.append(
            {
                "attribute": "id",
                "value": node.get("value") or node.get_text(" ", strip=True),
                "contains_target": TARGET_PRODUCT_ID in str(
                    node.get("value") or node.get_text(" ", strip=True)
                ).split(","),
            }
        )
    for node in soup.find_all(
        attrs={"name": re.compile(r"^af_controller_product_ids$", re.I)}
    ):
        out.append(
            {
                "attribute": "name",
                "value": node.get("value") or node.get_text(" ", strip=True),
                "contains_target": TARGET_PRODUCT_ID in str(
                    node.get("value") or node.get_text(" ", strip=True)
                ).split(","),
            }
        )
    return out[:20]


def _resolver_checks(ce, page_base: str) -> dict[str, Any]:
    resolver = (
        page_base.rstrip("/")
        + "/index.php?controller=product&id_product="
        + TARGET_PRODUCT_ID
    )
    return {
        "resolver_url": resolver,
        "html_product_url_on_resolver": ce._html_product_url(
            "sabina", resolver, page_base
        ),
        "html_product_url_on_target": ce._html_product_url(
            "sabina", TARGET_PRODUCT_URL, page_base
        ),
    }


@router.get("/diagnose-sabina-legacy-page")
def diagnose_sabina_legacy_page(
    q: str = Query("Liquid Brun", min_length=1, max_length=100),
    url: str = Query(DEFAULT_SEARCH_URL, min_length=1, max_length=1000),
):
    started = time.perf_counter()
    ce = _load_engine()

    # The q parameter is informational only. The supplied URL is fetched
    # exactly as requested so this diagnostic never changes the retailer query.
    resp = ce._http_fetch(url, timeout=min(float(getattr(ce, "HTTP_TIMEOUT", 15)), 20.0))
    elapsed = round(time.perf_counter() - started, 3)

    data = resp.get("data") or b""
    final_url = resp.get("url") or url
    raw = data.decode("utf-8", "ignore") if isinstance(data, (bytes, bytearray)) else str(data or "")

    legacy_urls = sorted(ce._sabina_legacy_product_urls(data, final_url))
    target_legacy_urls = [u for u in legacy_urls if TARGET_PRODUCT_ID in u]
    href_matches = _matching_hrefs(data, final_url)
    hidden = _hidden_id_evidence(data)

    target_in_html = TARGET_PRODUCT_ID in raw
    target_url_in_html = TARGET_PRODUCT_URL.casefold() in urllib.parse.unquote(raw).casefold()
    target_slug_in_html = "41708-liquid-brun-limited-edition-extrait-de-parfum".casefold() in urllib.parse.unquote(raw).casefold()

    product_url_from_href = []
    for row in href_matches:
        resolved = ce._html_product_url("sabina", row["absolute"], final_url)
        product_url_from_href.append(
            {
                **row,
                "html_product_url_result": resolved,
                "accepted_as_product": bool(resolved),
            }
        )

    parser_ids = []
    for resolver in target_legacy_urls:
        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(resolver).query)
        parser_ids.extend(parsed.get("id_product", []))

    return {
        "diagnostic": "sabina-legacy-single-page-v1",
        "ok": True,
        "query_parameter": q,
        "requested_url": url,
        "http": {
            "status": resp.get("status"),
            "final_url": final_url,
            "content_type": resp.get("content_type"),
            "bytes": resp.get("length", len(data)),
            "diagnostic": ce._diagnostic(resp, url),
        },
        "target": {
            "product_id": TARGET_PRODUCT_ID,
            "canonical_product_url": TARGET_PRODUCT_URL,
            "target_id_present_in_html": target_in_html,
            "target_canonical_url_present_in_html": target_url_in_html,
            "target_slug_present_in_html": target_slug_in_html,
        },
        "legacy_hidden_field": hidden,
        "legacy_parser": {
            "total_resolver_urls": len(legacy_urls),
            "target_resolver_urls": target_legacy_urls,
            "target_ids_recovered": sorted(set(parser_ids)),
            "target_recovered": TARGET_PRODUCT_ID in set(parser_ids),
        },
        "href_extraction": {
            "target_matching_hrefs": product_url_from_href,
            "target_href_count": len(product_url_from_href),
        },
        "resolver_and_url_acceptance": _resolver_checks(ce, final_url),
        "interpretation": (
            "PARSER_SEES_TARGET" if TARGET_PRODUCT_ID in set(parser_ids)
            else "PARSER_DOES_NOT_SEE_TARGET"
        ),
        "elapsed_sec": elapsed,
        "read_only": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "catalog_resync_called": False,
    }

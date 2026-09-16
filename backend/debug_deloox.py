from __future__ import annotations

import re
import traceback
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])


# ============================================================
# TEST 1 — DELOOX DISCOVERY DIAGNOSTIC
# ============================================================
#
# SOLO DIAGNOSTICA.
#
# NON modifica:
#   - scraper.py
#   - sitecustomize.py
#   - ProductMatcher
#   - family_registry
#
# NON esegue:
#   - search()
#   - parse_product()
#
# Obiettivo:
#
#   Deloox HTML
#        ↓
#   RAW product URLs
#        ↓
#   current discover()
#        ↓
#   confronto
#
# ============================================================


DELOOX_BASE = "https://www.deloox.be"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": (
        "en-US,en;q=0.9,nl;q=0.8,fr;q=0.7"
    ),
}

TIMEOUT = (5.0, 15.0)


BORN_IN_ROMA_VARIANTS = [
    "Born in Roma Uomo",
    "Born in Roma Uomo Intense",
    "Born in Roma Uomo Extradose",
    "Born in Roma Uomo Green Stravaganza",
    "Born in Roma Uomo Coral Fantasy",
    "Born in Roma Uomo Yellow Dream",
    "Born in Roma Uomo Purple Melancholia",
    "Born in Roma Uomo The Gold",
    "Born in Roma Uomo Ivory",
    "Born in Roma Donna",
    "Born in Roma Donna Intense",
    "Born in Roma Donna Extradose",
    "Born in Roma Donna Green Stravaganza",
    "Born in Roma Donna Coral Fantasy",
    "Born in Roma Donna Yellow Dream",
    "Born in Roma Donna Purple Melancholia",
    "Born in Roma Donna The Gold",
    "Born in Roma Donna Ivory",
]


def clean_text(value: str) -> str:
    return " ".join(
        str(value or "").split()
    ).strip()


def norm(value: str) -> str:
    value = clean_text(value).lower()

    value = value.replace("’", "'")
    value = value.replace("-", " ")
    value = value.replace("_", " ")

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def variant_match(text: str) -> list[str]:
    """
    Cerca le varianti Born in Roma nel testo.

    Le varianti più lunghe vengono controllate prima.
    """

    normalized = norm(text)

    matches = []

    variants = sorted(
        BORN_IN_ROMA_VARIANTS,
        key=lambda x: len(norm(x)),
        reverse=True,
    )

    for variant in variants:
        if norm(variant) in normalized:
            matches.append(variant)

    return matches


def extract_slug(url: str) -> str:
    value = str(url or "").split("?", 1)[0]
    value = value.rstrip("/")

    if "/" not in value:
        return value

    return value.rsplit("/", 1)[-1]


def query_token_hits(
    text: str,
    query: str,
) -> dict:
    text_norm = norm(text)

    query_tokens = [
        token
        for token in norm(query).split()
        if token
    ]

    hits = []
    misses = []

    for token in query_tokens:
        if token in text_norm:
            hits.append(token)
        else:
            misses.append(token)

    return {
        "query_tokens": query_tokens,
        "hits": hits,
        "misses": misses,
        "hit_count": len(hits),
        "token_count": len(query_tokens),
    }


def collect_card_context(
    anchor,
    max_parents: int = 7,
) -> tuple[str, str]:

    anchor_text = clean_text(
        anchor.get_text(
            " ",
            strip=True,
        )
    )

    best_context = anchor_text

    node = anchor

    price_re = re.compile(
        r"(?:€\s*)?"
        r"\d{1,4}"
        r"\s*[.,]\s*"
        r"\d{2}"
        r"(?:\s*€)?"
    )

    for _ in range(max_parents):

        node = node.parent

        if not node:
            break

        context = clean_text(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if (
            len(context) > len(best_context)
            and len(context) <= 1800
        ):
            best_context = context

        if price_re.search(context):
            break

    return (
        anchor_text,
        best_context,
    )


def raw_search_page(
    session: requests.Session,
    endpoint: str,
    query: str,
    page_number: int,
    product_url,
    relevant,
) -> dict:

    result = {
        "page": page_number,
        "requested": endpoint,
    }

    try:

        response = session.get(
            endpoint,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        html = response.text or ""

        result.update(
            {
                "status_code": response.status_code,
                "final_url": response.url,
                "html_length": len(html),
            }
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        all_product_urls = {}
        relevant_product_urls = {}
        born_in_roma_urls = {}

        for anchor in soup.find_all(
            "a",
            href=True,
        ):

            raw_href = str(
                anchor.get("href") or ""
            )

            href = urljoin(
                response.url,
                raw_href,
            )

            normalized_url = product_url(
                href
            )

            if not normalized_url:
                continue

            anchor_text, context = (
                collect_card_context(anchor)
            )

            combined = (
                f"{anchor_text} "
                f"{context} "
                f"{normalized_url}"
            )

            token_info = query_token_hits(
                combined,
                query,
            )

            relevant_to_query = bool(
                relevant(
                    combined,
                    query,
                )
            )

            variants = variant_match(
                combined
            )

            entry = {
                "url": normalized_url,
                "slug": extract_slug(
                    normalized_url
                ),
                "anchor_text": anchor_text[:500],
                "context": context[:1800],
                "query_relevant": relevant_to_query,
                "query_token_hits": token_info,
                "born_in_roma_variant_matches": variants,
            }

            all_product_urls[
                normalized_url
            ] = entry

            if relevant_to_query:
                relevant_product_urls[
                    normalized_url
                ] = entry

            if variants:
                born_in_roma_urls[
                    normalized_url
                ] = entry

        result.update(
            {
                "raw_product_url_count": len(
                    all_product_urls
                ),
                "raw_relevant_url_count": len(
                    relevant_product_urls
                ),
                "raw_born_in_roma_url_count": len(
                    born_in_roma_urls
                ),
                "raw_product_urls": list(
                    all_product_urls.values()
                )[:300],
                "raw_relevant_urls": list(
                    relevant_product_urls.values()
                )[:300],
                "raw_born_in_roma_urls": list(
                    born_in_roma_urls.values()
                )[:300],
            }
        )

        return result

    except Exception as exc:

        result.update(
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

        return result


def compare_discovery(
    raw_pages: list[dict],
    candidates: list,
) -> dict:

    raw_entries = {}

    for page in raw_pages:

        for entry in page.get(
            "raw_born_in_roma_urls",
            [],
        ):

            url = entry.get("url")

            if url:
                raw_entries[url] = entry

    discovered = {}

    for item in candidates:

        try:
            url, info = item

            discovered[url] = {
                "url": url,
                "score": info[0],
                "context": info[1][:1800],
                "variant_matches": variant_match(
                    f"{url} {info[1]}"
                ),
            }

        except Exception:
            continue

    raw_urls = set(
        raw_entries.keys()
    )

    discovered_urls = set(
        discovered.keys()
    )

    raw_not_discovered = sorted(
        raw_urls - discovered_urls
    )

    discovered_not_raw = sorted(
        discovered_urls - raw_urls
    )

    return {
        "raw_born_in_roma_unique_urls": len(
            raw_urls
        ),
        "discover_unique_urls": len(
            discovered_urls
        ),
        "born_in_roma_found_in_raw_but_missing_from_discover_count": len(
            raw_not_discovered
        ),
        "discover_urls_not_classified_as_born_in_roma_by_raw_pages_count": len(
            discovered_not_raw
        ),
        "born_in_roma_found_in_raw_but_missing_from_discover": [
            {
                "url": url,
                "slug": extract_slug(url),
                "variant_matches": (
                    raw_entries[url].get(
                        "born_in_roma_variant_matches",
                        [],
                    )
                ),
                "raw_entry": raw_entries.get(url),
            }
            for url in raw_not_discovered
        ],
        "discover_urls_not_classified_as_born_in_roma_by_raw_pages": [
            {
                "url": url,
                "slug": extract_slug(url),
                "discover_entry": discovered.get(url),
            }
            for url in discovered_not_raw
        ],
    }


@router.get("/deloox-discovery")
def debug_deloox_discovery(
    q: str = Query(
        "Born in Roma",
        min_length=2,
    )
):

    session = None

    try:

        # Importiamo SOLO le funzioni che sappiamo
        # essere necessarie dal file scraper.
        #
        # BASE / HEADERS / TIMEOUT NON vengono importati.
        from scrapers.deloox.scraper import (
            discover,
            product_url,
            relevant,
        )

        query = str(
            q or ""
        ).strip()

        encoded = quote_plus(
            query
        )

        session = requests.Session()

        raw_pages = []

        # ----------------------------------------------------
        # TEST DIRECT HTML
        # ----------------------------------------------------

        for page_number in range(1, 11):

            if page_number == 1:

                endpoint = (
                    f"{DELOOX_BASE}/chercher.html"
                    f"?q={encoded}"
                )

            else:

                endpoint = (
                    f"{DELOOX_BASE}/chercher.html"
                    f"?q={encoded}"
                    f"&page={page_number}"
                )

            page_result = raw_search_page(
                session=session,
                endpoint=endpoint,
                query=query,
                page_number=page_number,
                product_url=product_url,
                relevant=relevant,
            )

            raw_pages.append(
                page_result
            )

            # Se non troviamo nessun product URL,
            # non continuiamo con altre pagine.
            if (
                page_result.get(
                    "raw_product_url_count",
                    0,
                )
                == 0
            ):
                break

        # ----------------------------------------------------
        # CURRENT DISCOVER()
        # ----------------------------------------------------

        candidates = []
        discover_error = None

        try:

            candidates = discover(
                session,
                query,
            )

        except Exception as exc:

            discover_error = {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

        # ----------------------------------------------------
        # DETAILED DISCOVER RESULTS
        # ----------------------------------------------------

        discover_rows = []

        for index, item in enumerate(
            candidates
        ):

            try:

                url, info = item

                score = info[0]
                context = info[1]

                combined = (
                    f"{url} "
                    f"{context}"
                )

                discover_rows.append(
                    {
                        "index": index,
                        "url": url,
                        "slug": extract_slug(url),
                        "score": score,
                        "query_relevant": bool(
                            relevant(
                                combined,
                                query,
                            )
                        ),
                        "query_token_hits": (
                            query_token_hits(
                                combined,
                                query,
                            )
                        ),
                        "born_in_roma_variant_matches": (
                            variant_match(
                                combined
                            )
                        ),
                        "context": context[:1800],
                    }
                )

            except Exception as exc:

                discover_rows.append(
                    {
                        "index": index,
                        "parse_error": True,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "raw_item": repr(item),
                    }
                )

        comparison = compare_discovery(
            raw_pages,
            candidates,
        )

        # ----------------------------------------------------
        # VARIANT SUMMARY
        # ----------------------------------------------------

        raw_variant_urls = {}

        for page in raw_pages:

            for entry in page.get(
                "raw_born_in_roma_urls",
                [],
            ):

                url = entry.get("url")

                if not url:
                    continue

                variants = entry.get(
                    "born_in_roma_variant_matches",
                    [],
                )

                for variant in variants:

                    raw_variant_urls.setdefault(
                        variant,
                        [],
                    ).append(
                        url
                    )

        discovered_variant_urls = {}

        for row in discover_rows:

            for variant in row.get(
                "born_in_roma_variant_matches",
                [],
            ):

                url = row.get("url")

                if not url:
                    continue

                discovered_variant_urls.setdefault(
                    variant,
                    [],
                ).append(
                    url
                )

        for mapping in (
            raw_variant_urls,
            discovered_variant_urls,
        ):

            for key in mapping:

                mapping[key] = sorted(
                    set(
                        value
                        for value in mapping[key]
                        if value
                    )
                )

        return {
            "diagnostic": True,
            "test": "TEST_1_DISCOVERY_ONLY",
            "ok": discover_error is None,
            "store": "Deloox",
            "query": query,

            "important": (
                "Discovery-only diagnostic. "
                "Product pages and JSON-LD are NOT inspected."
            ),

            "expected_family_variant_count": len(
                BORN_IN_ROMA_VARIANTS
            ),

            "expected_family_variants": (
                BORN_IN_ROMA_VARIANTS
            ),

            "raw_search_pages_checked": len(
                raw_pages
            ),

            "raw_pages": raw_pages,

            "discover_error": discover_error,

            "discover_candidate_count": len(
                candidates
            ),

            "discover_candidates": discover_rows,

            "comparison": comparison,

            "raw_variant_urls": raw_variant_urls,

            "discovered_variant_urls": (
                discovered_variant_urls
            ),
        }

    except Exception as exc:

        return {
            "diagnostic": True,
            "test": "TEST_1_DISCOVERY_ONLY",
            "ok": False,
            "store": "Deloox",
            "query": q,
            "stage": "debug_deloox_discovery",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

    finally:

        if session is not None:

            try:
                session.close()
            except Exception:
                pass


# ============================================================
# COMPATIBILITY ENDPOINT
# ============================================================


@router.get("/deloox")
def debug_deloox(
    q: str = Query(
        ...,
        min_length=2,
    )
):
    """
    Manteniamo il vecchio endpoint.

    Per il Test 1 possiamo quindi usare sia:

        /api/debug/deloox?q=Born+in+Roma

    sia:

        /api/debug/deloox-discovery?q=Born+in+Roma
    """

    return debug_deloox_discovery(
        q=q
    )

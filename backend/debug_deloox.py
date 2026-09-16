from __future__ import annotations

import re
import traceback
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])

DELOOX_BASE = "https://www.deloox.be"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8,fr;q=0.7",
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
    return " ".join(str(value or "").split()).strip()


def norm(value: str) -> str:
    value = clean_text(value).lower()
    value = value.replace("’", "'")
    value = value.replace("-", " ")
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def variant_match(text: str) -> list[str]:
    normalized = norm(text)
    matches = []

    for variant in sorted(
        BORN_IN_ROMA_VARIANTS,
        key=lambda x: len(norm(x)),
        reverse=True,
    ):
        if norm(variant) in normalized:
            matches.append(variant)

    return matches


def extract_slug(url: str) -> str:
    value = str(url or "").split("?", 1)[0].rstrip("/")
    return value.rsplit("/", 1)[-1] if "/" in value else value


def query_token_hits(text: str, query: str) -> dict:
    text_norm = norm(text)
    query_tokens = [x for x in norm(query).split() if x]

    hits = [token for token in query_tokens if token in text_norm]
    misses = [token for token in query_tokens if token not in text_norm]

    return {
        "query_tokens": query_tokens,
        "hits": hits,
        "misses": misses,
        "hit_count": len(hits),
        "token_count": len(query_tokens),
    }


def collect_card_context(anchor, max_parents: int = 7) -> tuple[str, str]:
    anchor_text = clean_text(anchor.get_text(" ", strip=True))
    best_context = anchor_text
    node = anchor

    price_re = re.compile(
        r"(?:€\s*)?\d{1,4}\s*[.,]\s*\d{2}(?:\s*€)?"
    )

    for _ in range(max_parents):
        node = node.parent
        if not node:
            break

        context = clean_text(node.get_text(" ", strip=True))

        if len(context) > len(best_context) and len(context) <= 1800:
            best_context = context

        if price_re.search(context):
            break

    return anchor_text, best_context


def raw_search_page(
    session: requests.Session,
    endpoint: str,
    query: str,
    page_number: int,
    product_url,
    relevant,
) -> dict:
    result = {"page": page_number, "requested": endpoint}

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

        soup = BeautifulSoup(html, "html.parser")

        all_product_urls = {}
        relevant_product_urls = {}
        born_in_roma_urls = {}

        for anchor in soup.find_all("a", href=True):
            href = urljoin(
                response.url,
                str(anchor.get("href") or ""),
            )

            normalized_url = product_url(href)
            if not normalized_url:
                continue

            anchor_text, context = collect_card_context(anchor)

            combined = (
                f"{anchor_text} {context} {normalized_url}"
            )

            entry = {
                "url": normalized_url,
                "slug": extract_slug(normalized_url),
                "anchor_text": anchor_text[:500],
                "context": context[:1800],
                "query_relevant": bool(relevant(combined, query)),
                "query_token_hits": query_token_hits(combined, query),
                "born_in_roma_variant_matches": variant_match(combined),
            }

            all_product_urls[normalized_url] = entry

            if entry["query_relevant"]:
                relevant_product_urls[normalized_url] = entry

            if entry["born_in_roma_variant_matches"]:
                born_in_roma_urls[normalized_url] = entry

        result.update(
            {
                "raw_product_url_count": len(all_product_urls),
                "raw_relevant_url_count": len(relevant_product_urls),
                "raw_born_in_roma_url_count": len(born_in_roma_urls),
                "raw_product_urls": list(all_product_urls.values())[:300],
                "raw_relevant_urls": list(relevant_product_urls.values())[:300],
                "raw_born_in_roma_urls": list(born_in_roma_urls.values())[:300],
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


def compare_discovery(raw_pages: list[dict], candidates: list) -> dict:
    raw_entries = {}

    for page in raw_pages:
        for entry in page.get("raw_born_in_roma_urls", []):
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

    raw_urls = set(raw_entries)
    discovered_urls = set(discovered)

    raw_not_discovered = sorted(raw_urls - discovered_urls)
    discovered_not_raw = sorted(discovered_urls - raw_urls)

    return {
        "raw_born_in_roma_unique_urls": len(raw_urls),
        "discover_unique_urls": len(discovered_urls),
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
                "variant_matches": raw_entries[url].get(
                    "born_in_roma_variant_matches", []
                ),
                "raw_entry": raw_entries[url],
            }
            for url in raw_not_discovered
        ],
        "discover_urls_not_classified_as_born_in_roma_by_raw_pages": [
            {
                "url": url,
                "slug": extract_slug(url),
                "discover_entry": discovered[url],
            }
            for url in discovered_not_raw
        ],
    }


@router.get("/deloox-discovery")
def debug_deloox_discovery(
    q: str = Query("Born in Roma", min_length=2),
):
    session = None

    try:
        from scrapers.deloox.scraper import (
            discover,
            product_url,
            relevant,
        )

        query = str(q or "").strip()
        encoded = quote_plus(query)
        session = requests.Session()
        raw_pages = []

        for page_number in range(1, 11):
            if page_number == 1:
                endpoint = (
                    f"{DELOOX_BASE}/chercher.html"
                    f"?q={encoded}"
                )
            else:
                endpoint = (
                    f"{DELOOX_BASE}/chercher.html"
                    f"?q={encoded}&page={page_number}"
                )

            page_result = raw_search_page(
                session=session,
                endpoint=endpoint,
                query=query,
                page_number=page_number,
                product_url=product_url,
                relevant=relevant,
            )

            raw_pages.append(page_result)

            if page_result.get("raw_product_url_count", 0) == 0:
                break

        candidates = []
        discover_error = None

        try:
            candidates = discover(session, query)
        except Exception as exc:
            discover_error = {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

        discover_rows = []

        for index, item in enumerate(candidates):
            try:
                url, info = item
                score, context = info
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
                continue

            combined = f"{url} {context}"

            discover_rows.append(
                {
                    "index": index,
                    "url": url,
                    "slug": extract_slug(url),
                    "score": score,
                    "query_relevant": bool(
                        relevant(combined, query)
                    ),
                    "query_token_hits": query_token_hits(
                        combined,
                        query,
                    ),
                    "born_in_roma_variant_matches": variant_match(
                        combined
                    ),
                    "context": str(context or "")[:1800],
                }
            )

        comparison = compare_discovery(
            raw_pages,
            candidates,
        )

        raw_variant_urls = {}

        for page in raw_pages:
            for entry in page.get("raw_born_in_roma_urls", []):
                url = entry.get("url")
                if not url:
                    continue

                for variant in entry.get(
                    "born_in_roma_variant_matches",
                    [],
                ):
                    raw_variant_urls.setdefault(
                        variant,
                        [],
                    ).append(url)

        discovered_variant_urls = {}

        for row in discover_rows:
            url = row.get("url")
            if not url:
                continue

            for variant in row.get(
                "born_in_roma_variant_matches",
                [],
            ):
                discovered_variant_urls.setdefault(
                    variant,
                    [],
                ).append(url)

        for mapping in (
            raw_variant_urls,
            discovered_variant_urls,
        ):
            for key in mapping:
                mapping[key] = sorted(set(mapping[key]))

        return {
            "diagnostic": True,
            "test": "TEST_1_DISCOVERY_ONLY",
            "ok": discover_error is None,
            "store": "Deloox",
            "query": query,
            "important": (
                "Discovery-only diagnostic. "
                "Product pages and matching are NOT inspected."
            ),
            "expected_family_variant_count": len(
                BORN_IN_ROMA_VARIANTS
            ),
            "expected_family_variants": BORN_IN_ROMA_VARIANTS,
            "raw_search_pages_checked": len(raw_pages),
            "raw_pages": raw_pages,
            "discover_error": discover_error,
            "discover_candidate_count": len(candidates),
            "discover_candidates": discover_rows,
            "comparison": comparison,
            "raw_variant_urls": raw_variant_urls,
            "discovered_variant_urls": discovered_variant_urls,
        }

    except Exception as exc:
        return {
            "diagnostic": True,
            "test": "TEST_1_DISCOVERY_ONLY",
            "ok": False,
            "store": "Deloox",
            "query": str(q or "").strip(),
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


@router.get("/deloox")
def debug_deloox_legacy(
    q: str = Query("Born in Roma", min_length=2),
):
    return debug_deloox_discovery(q=q)


@router.get("/deloox-pipeline")
def debug_deloox_pipeline(
    q: str = Query("Born in Roma", min_length=2),
):
    session = None

    try:
        from scrapers.deloox.scraper import (
            discover,
            _row_from_card,
            parse_product,
        )

        query = str(q or "").strip()
        session = requests.Session()

        candidates = []
        discover_error = None

        try:
            candidates = discover(session, query)
        except Exception as exc:
            discover_error = {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

        if discover_error:
            return {
                "diagnostic": True,
                "test": "TEST_2_PIPELINE",
                "ok": False,
                "store": "Deloox",
                "query": query,
                "stage": "discover",
                "discover_error": discover_error,
            }

        card_accepted = []
        card_rejected = []
        product_page_results = []
        discovered_rows = []

        seen = set()

        for index, item in enumerate(candidates):
            try:
                url, info = item
                score, context = info
            except Exception as exc:
                discovered_rows.append(
                    {
                        "index": index,
                        "stage": "DISCOVERED_PARSE_ERROR",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "raw_item": repr(item),
                    }
                )
                continue

            if url in seen:
                continue

            seen.add(url)

            base = {
                "index": index,
                "url": url,
                "slug": extract_slug(url),
                "score": score,
                "context": str(context or "")[:1800],
            }

            card_result = None
            card_error = None

            try:
                card_result = _row_from_card(
                    url,
                    context,
                    query,
                )
            except Exception as exc:
                card_error = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }

            if isinstance(card_result, dict):
                row = dict(base)
                row.update(
                    {
                        "stage": "CARD_ACCEPTED",
                        "card_row": card_result,
                        "card_name": card_result.get("name"),
                        "card_brand": card_result.get("brand"),
                        "card_price": card_result.get("price"),
                        "card_price_num": card_result.get("price_num"),
                        "card_available": card_result.get("available"),
                        "card_availability": card_result.get(
                            "availability"
                        ),
                        "card_size_ml": card_result.get("size_ml"),
                        "born_in_roma_variant_matches": variant_match(
                            " ".join(
                                [
                                    url,
                                    str(context or ""),
                                    str(card_result.get("name") or ""),
                                ]
                            )
                        ),
                    }
                )
                card_accepted.append(row)
                discovered_rows.append(row)
                continue

            row = dict(base)
            row.update(
                {
                    "stage": "CARD_REJECTED",
                    "card_error": card_error,
                    "card_return_type": (
                        type(card_result).__name__
                        if card_result is not None
                        else "None"
                    ),
                    "drop_reason": (
                        "CARD_EXCEPTION"
                        if card_error
                        else "CARD_RETURNED_NONE"
                    ),
                    "born_in_roma_variant_matches": variant_match(
                        f"{url} {context}"
                    ),
                }
            )

            card_rejected.append(row)
            discovered_rows.append(row)

            # ------------------------------------------------
            # PRODUCT PAGE FALLBACK
            # ------------------------------------------------
            try:
                rows = parse_product(url, query) or []

                if rows:
                    product_page_results.append(
                        {
                            "index": index,
                            "url": url,
                            "slug": extract_slug(url),
                            "stage": "PRODUCT_PAGE_OK",
                            "row_count": len(rows),
                            "rows": rows,
                            "drop_reason": None,
                            "born_in_roma_variant_matches": variant_match(
                                f"{url} {context} "
                                + " ".join(
                                    str(r.get("name") or "")
                                    for r in rows
                                    if isinstance(r, dict)
                                )
                            ),
                        }
                    )
                else:
                    product_page_results.append(
                        {
                            "index": index,
                            "url": url,
                            "slug": extract_slug(url),
                            "stage": "PRODUCT_PAGE_REJECTED",
                            "row_count": 0,
                            "rows": [],
                            "drop_reason": (
                                "PARSE_PRODUCT_RETURNED_EMPTY"
                            ),
                            "born_in_roma_variant_matches": variant_match(
                                f"{url} {context}"
                            ),
                        }
                    )

            except Exception as exc:
                product_page_results.append(
                    {
                        "index": index,
                        "url": url,
                        "slug": extract_slug(url),
                        "stage": "PRODUCT_PAGE_EXCEPTION",
                        "row_count": 0,
                        "rows": [],
                        "drop_reason": "PARSE_PRODUCT_EXCEPTION",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                        "born_in_roma_variant_matches": variant_match(
                            f"{url} {context}"
                        ),
                    }
                )

        final_rows = []

        for item in card_accepted:
            final_rows.append(
                {
                    "index": item["index"],
                    "url": item["url"],
                    "slug": item["slug"],
                    "stage": "FINAL_CARD_ACCEPTED",
                    "name": item.get("card_name"),
                    "brand": item.get("card_brand"),
                    "price": item.get("card_price"),
                    "price_num": item.get("card_price_num"),
                    "available": item.get("card_available"),
                    "availability": item.get("card_availability"),
                    "size_ml": item.get("card_size_ml"),
                    "born_in_roma_variant_matches": item.get(
                        "born_in_roma_variant_matches",
                        [],
                    ),
                }
            )

        for item in product_page_results:
            if item.get("stage") != "PRODUCT_PAGE_OK":
                continue

            for row in item.get("rows", []):
                if not isinstance(row, dict):
                    continue

                final_rows.append(
                    {
                        "index": item["index"],
                        "url": item["url"],
                        "slug": item["slug"],
                        "stage": "FINAL_PRODUCT_ACCEPTED",
                        "name": row.get("name"),
                        "brand": row.get("brand"),
                        "price": row.get("price"),
                        "price_num": row.get("price_num"),
                        "available": row.get("available"),
                        "availability": row.get("availability"),
                        "size_ml": row.get("size_ml"),
                        "born_in_roma_variant_matches": variant_match(
                            " ".join(
                                [
                                    item["url"],
                                    str(row.get("name") or ""),
                                    str(row.get("brand") or ""),
                                ]
                            )
                        ),
                    }
                )

        return {
            "diagnostic": True,
            "test": "TEST_2_PIPELINE",
            "ok": True,
            "store": "Deloox",
            "query": query,
            "important": (
                "Pipeline diagnostic only. "
                "ProductMatcher and family_registry are NOT executed."
            ),
            "counts": {
                "discover_candidates": len(candidates),
                "unique_discovered": len(seen),
                "card_accepted": len(card_accepted),
                "card_rejected": len(card_rejected),
                "product_page_tested": len(product_page_results),
                "product_page_ok": sum(
                    1
                    for x in product_page_results
                    if x.get("stage") == "PRODUCT_PAGE_OK"
                ),
                "product_page_rejected": sum(
                    1
                    for x in product_page_results
                    if x.get("stage") == "PRODUCT_PAGE_REJECTED"
                ),
                "product_page_exception": sum(
                    1
                    for x in product_page_results
                    if x.get("stage") == "PRODUCT_PAGE_EXCEPTION"
                ),
                "final_rows": len(final_rows),
            },
            "discover_candidates": discovered_rows,
            "card_rejected": card_rejected,
            "product_page_results": product_page_results,
            "final_rows": final_rows,
        }

    except Exception as exc:
        return {
            "diagnostic": True,
            "test": "TEST_2_PIPELINE",
            "ok": False,
            "store": "Deloox",
            "query": str(q or "").strip(),
            "stage": "diagnostic_exception",
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
# TEST 3 — Deloox: analisi profonda della pagina prodotto
# ============================================================

from urllib.parse import urlparse
import json
import re

@app.get("/api/debug/deloox-product")
def debug_deloox_product(q: str = "Born in Roma"):
    from backend.scrapers.deloox.scraper import (
        clean,
        norm,
        discover,
        product_url,
        relevant,
        non_fragrance,
        _row_from_card,
        parse_product,
    )

    session = requests.Session()
    session.headers.update(HEADERS)

    result = {
        "ok": True,
        "test": "TEST_3_PRODUCT_PAGE_DEEP",
        "query": q,
        "products": [],
        "summary": {}
    }

    try:
        candidates = discover(session, q)

        # Prendiamo solo candidati il cui URL sembra realmente Born in Roma.
        born_candidates = []

        for item in candidates:
            try:
                url, context = item
            except Exception:
                continue

            slug = extract_slug(url).lower()

            if "born-in-roma" in slug or "born-in-roma" in norm(context).replace(" ", "-"):
                born_candidates.append((url, context))

        # Se il filtro fosse troppo restrittivo, prendiamo comunque
        # i primi candidati per non perdere il problema.
        if not born_candidates:
            born_candidates = candidates[:10]

        for url, context in born_candidates[:20]:

            item = {
                "url": url,
                "slug": extract_slug(url),
                "context": clean(context)[:1200],
            }

            # ------------------------------------------------
            # A. _row_from_card
            # ------------------------------------------------
            try:
                card_row = _row_from_card(url, context, q)

                if isinstance(card_row, dict):
                    item["card"] = {
                        "status": "ACCEPTED",
                        "row": card_row
                    }
                else:
                    item["card"] = {
                        "status": "REJECTED",
                        "reason": "row_from_card returned non-dict",
                        "type": str(type(card_row))
                    }

            except Exception as e:
                item["card"] = {
                    "status": "EXCEPTION",
                    "error": repr(e)
                }

            # ------------------------------------------------
            # B. PAGINA PRODOTTO RAW
            # ------------------------------------------------
            try:
                r = session.get(url, timeout=TIMEOUT)

                item["product_page"] = {
                    "http_status": r.status_code,
                    "html_length": len(r.text),
                    "content_type": r.headers.get("content-type")
                }

                soup = BeautifulSoup(r.text, "html.parser")

                # JSON-LD
                jsonld_nodes = []

                for script in soup.find_all(
                    "script",
                    attrs={"type": re.compile(r"application/ld\+json", re.I)}
                ):
                    raw = script.string or script.get_text()

                    if not raw:
                        continue

                    try:
                        data = json.loads(raw)

                        if isinstance(data, list):
                            jsonld_nodes.extend(data)
                        else:
                            jsonld_nodes.append(data)

                    except Exception as e:
                        jsonld_nodes.append({
                            "_json_parse_error": repr(e),
                            "_raw_preview": clean(raw)[:500]
                        })

                item["jsonld_count"] = len(jsonld_nodes)

                products = []

                for node in jsonld_nodes:
                    if not isinstance(node, dict):
                        continue

                    node_type = node.get("@type")

                    types = node_type if isinstance(node_type, list) else [node_type]

                    if (
                        "Product" in types
                        or "ProductGroup" in types
                        or node.get("name")
                        or node.get("offers")
                    ):
                        products.append({
                            "@type": node_type,
                            "name": node.get("name"),
                            "brand": node.get("brand"),
                            "sku": node.get("sku"),
                            "gtin": (
                                node.get("gtin")
                                or node.get("gtin13")
                                or node.get("gtin12")
                                or node.get("gtin14")
                            ),
                            "offers": node.get("offers"),
                            "availability": node.get("availability"),
                            "url": node.get("url")
                        })

                item["jsonld_products"] = products[:10]

                # ------------------------------------------------
                # C. TEST DELLE FUNZIONI DI FILTRO
                # ------------------------------------------------
                names = []

                for p in products:
                    name = p.get("name")
                    if name:
                        names.append(name)

                item["name_tests"] = []

                for name in names:
                    item["name_tests"].append({
                        "name": name,
                        "relevant": relevant(name, q),
                        "non_fragrance": non_fragrance(name),
                        "norm": norm(name)
                    })

                # ------------------------------------------------
                # D. parse_product REALE
                # ------------------------------------------------
                try:
                    parsed = parse_product(session, url, q)

                    item["parse_product"] = {
                        "status": "ACCEPTED" if parsed else "REJECTED",
                        "count": len(parsed) if parsed else 0,
                        "rows": parsed or []
                    }

                except Exception as e:
                    item["parse_product"] = {
                        "status": "EXCEPTION",
                        "error": repr(e)
                    }

            except Exception as e:
                item["product_page"] = {
                    "status": "EXCEPTION",
                    "error": repr(e)
                }

            result["products"].append(item)

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------
        result["summary"] = {
            "discover_candidates": len(candidates),
            "born_candidates_tested": len(result["products"]),
            "card_accepted": sum(
                1 for x in result["products"]
                if x.get("card", {}).get("status") == "ACCEPTED"
            ),
            "card_rejected": sum(
                1 for x in result["products"]
                if x.get("card", {}).get("status") == "REJECTED"
            ),
            "card_exception": sum(
                1 for x in result["products"]
                if x.get("card", {}).get("status") == "EXCEPTION"
            ),
            "parse_accepted": sum(
                1 for x in result["products"]
                if x.get("parse_product", {}).get("status") == "ACCEPTED"
            ),
            "parse_rejected": sum(
                1 for x in result["products"]
                if x.get("parse_product", {}).get("status") == "REJECTED"
            ),
            "parse_exception": sum(
                1 for x in result["products"]
                if x.get("parse_product", {}).get("status") == "EXCEPTION"
            )
        }

        return result

    except Exception as e:
        return {
            "ok": False,
            "test": "TEST_3_PRODUCT_PAGE_DEEP",
            "query": q,
            "error": repr(e)
        }
 

from __future__ import annotations

import importlib
import re
import time
from urllib.parse import quote_plus, urljoin

from fastapi import APIRouter

router = APIRouter(prefix="/api/debug", tags=["debug-deloox"])


TARGET_ID = "1391716"
TARGET_NAME = "Valentino Born in Roma Purple Melancholia Donna"
DEFAULT_QUERY = "Born in Roma"


def _safe_call(fn, *args, **kwargs):
    try:
        return {
            "ok": True,
            "value": fn(*args, **kwargs),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _extract_target_urls_from_html(html: str, base: str):
    found = set()

    # Deloox product URLs in normal HTML / escaped JSON.
    patterns = [
        r'(?:https?:\\/\\/[^"\'<>\s]+)?/produit/\d+/[^"\'<>\s?#]+',
        r'(?:https?:\/\/[^"\'<>\s]+)?/produit/\d+/[^"\'<>\s?#]+',
    ]

    for pattern in patterns:
        for raw in re.findall(pattern, html or "", flags=re.I):
            raw = raw.replace("\\/", "/")
            if raw.startswith("/"):
                url = urljoin(base.rstrip("/") + "/", raw)
            elif raw.startswith("http"):
                url = raw
            else:
                continue

            url = url.split("#", 1)[0].split("?", 1)[0]

            if TARGET_ID in url:
                found.add(url)

    return sorted(found)


@router.get("/deloox-missing-purple-donna")
def deloox_missing_purple_donna(q: str = DEFAULT_QUERY):
    """
    TEST: trace Deloox product 1391716 (Donna Purple Melancholia)
    through:
        raw search HTML
        discover()
        _row_from_card()
        parse_product()
        search()

    This endpoint is diagnostic only.
    It does NOT modify the Deloox scraper or ProductMatcher.
    """

    out = {
        "ok": True,
        "test": "TEST_15_DELOOX_MISSING_PURPLE_DONNA_TRACE",
        "query": q,
        "target": {
            "id": TARGET_ID,
            "name": TARGET_NAME,
        },
    }

    try:
        m = importlib.import_module("scrapers.deloox.scraper")

        out["runtime"] = {
            "module_file": getattr(m, "__file__", ""),
            "module_name": getattr(m, "__name__", ""),
            "base": getattr(m, "BASE", ""),
            "max_candidates": getattr(m, "MAX_CANDIDATES", None),
            "born_max_candidates": getattr(
                m, "BORN_IN_ROMA_MAX_CANDIDATES", None
            ),
            "max_results": getattr(m, "MAX_RESULTS", None),
            "discover_signature": str(
                getattr(m, "discover", None)
            ),
            "search_signature": str(
                getattr(m, "search", None)
            ),
        }

        # Use the scraper's own requests/get machinery.
        requests_module = getattr(m, "requests", None)
        if requests_module is None:
            raise RuntimeError(
                "Runtime Deloox scraper has no requests module exposed"
            )

        session = requests_module.Session()

        base = getattr(m, "BASE", "https://www.deloox.be").rstrip("/")

        # ------------------------------------------------------------
        # 1. RAW SEARCH HTML
        # ------------------------------------------------------------
        raw_pages = []
        raw_target_urls = set()

        encoded = quote_plus(q)

        for page in range(1, 11):
            if page == 1:
                endpoint = f"{base}/chercher.html?q={encoded}"
            else:
                endpoint = (
                    f"{base}/chercher.html?q={encoded}&page={page}"
                )

            started = time.perf_counter()

            try:
                response = m.get(session, endpoint)

                if not response:
                    raw_pages.append({
                        "page": page,
                        "request_ok": False,
                        "status_code": None,
                        "html_length": 0,
                        "target_id_present": False,
                        "target_url_count": 0,
                        "elapsed": round(
                            time.perf_counter() - started, 3
                        ),
                    })
                    continue

                html = response.text or ""
                urls = _extract_target_urls_from_html(html, base)
                raw_target_urls.update(urls)

                raw_pages.append({
                    "page": page,
                    "request_ok": True,
                    "status_code": getattr(
                        response, "status_code", None
                    ),
                    "final_url": getattr(response, "url", ""),
                    "html_length": len(html),
                    "target_id_present": TARGET_ID in html,
                    "target_occurrences": html.count(TARGET_ID),
                    "target_url_count": len(urls),
                    "target_urls": urls,
                    "elapsed": round(
                        time.perf_counter() - started, 3
                    ),
                })

            except Exception as exc:
                raw_pages.append({
                    "page": page,
                    "request_ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "elapsed": round(
                        time.perf_counter() - started, 3
                    ),
                })

        out["raw_search"] = {
            "pages": raw_pages,
            "target_urls": sorted(raw_target_urls),
            "target_found": bool(raw_target_urls),
        }

        # ------------------------------------------------------------
        # 2. DIRECT PRODUCT URL + HELPERS
        # ------------------------------------------------------------
        target_url = (
            sorted(raw_target_urls)[0]
            if raw_target_urls
            else (
                f"{base}/produit/{TARGET_ID}/"
                "born-in-roma-purple-melancholia-donna-"
                "eau-de-parfum-30-ml.html"
            )
        )

        out["target_url"] = target_url

        direct = {
            "url": target_url,
        }

        try:
            started = time.perf_counter()
            response = m.get(session, target_url)
            direct["request"] = {
                "ok": bool(response),
                "status_code": (
                    getattr(response, "status_code", None)
                    if response
                    else None
                ),
                "final_url": (
                    getattr(response, "url", "")
                    if response
                    else ""
                ),
                "html_length": (
                    len(response.text or "")
                    if response
                    else 0
                ),
                "elapsed": round(
                    time.perf_counter() - started, 3
                ),
            }

            product_html = response.text if response else ""

            try:
                products = m.jsonld_products(product_html)
            except Exception as exc:
                products = []
                direct["jsonld_error"] = {
                    "type": type(exc).__name__,
                    "error": str(exc),
                }

            direct["jsonld_products"] = []

            for product in products or []:
                if not isinstance(product, dict):
                    continue

                offers = product.get("offers")

                direct["jsonld_products"].append({
                    "name": product.get("name"),
                    "brand": product.get("brand"),
                    "sku": product.get("sku"),
                    "url": product.get("url"),
                    "image": product.get("image"),
                    "offers": offers,
                })

        except Exception as exc:
            direct["request"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        # Helper checks.
        helper_inputs = {
            "is_product_url": (
                "is_product_url",
                (target_url,),
            ),
            "product_url": (
                "product_url",
                (target_url,),
            ),
            "born_in_roma_slug": (
                "born_in_roma_slug",
                (target_url,),
            ),
            "excluded_product_slug": (
                "excluded_product_slug",
                (target_url,),
            ),
            "relevant": (
                "relevant",
                (
                    TARGET_NAME
                    + " Eau de Parfum 30 ml",
                    q,
                ),
            ),
            "non_fragrance": (
                "non_fragrance",
                (
                    TARGET_NAME
                    + " Eau de Parfum 30 ml",
                ),
            ),
        }

        helpers = {}

        for name, (fn_name, args) in helper_inputs.items():
            fn = getattr(m, fn_name, None)

            if not callable(fn):
                helpers[name] = {
                    "exists": False,
                }
                continue

            try:
                helpers[name] = {
                    "exists": True,
                    "value": fn(*args),
                }
            except Exception as exc:
                helpers[name] = {
                    "exists": True,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

        direct["helpers"] = helpers
        out["direct_product"] = direct

        # ------------------------------------------------------------
        # 3. parse_product() DIRECT
        # ------------------------------------------------------------
        try:
            started = time.perf_counter()
            parsed = m.parse_product(target_url, q)

            out["parse_product"] = {
                "ok": True,
                "elapsed": round(
                    time.perf_counter() - started, 3
                ),
                "returned_type": type(parsed).__name__,
                "row_count": len(parsed or []),
                "rows": parsed or [],
            }

        except Exception as exc:
            out["parse_product"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        # ------------------------------------------------------------
        # 4. discover()
        # ------------------------------------------------------------
        try:
            started = time.perf_counter()
            candidates = m.discover(session, q)

            target_candidates = []

            for item in candidates or []:
                if not isinstance(item, (tuple, list)):
                    continue

                if len(item) < 1:
                    continue

                url = item[0]

                if TARGET_ID not in str(url):
                    continue

                info = item[1] if len(item) > 1 else None

                candidate = {
                    "url": url,
                    "info_type": type(info).__name__,
                    "info_repr": repr(info),
                }

                # ----------------------------------------------------
                # 5. _row_from_card()
                # ----------------------------------------------------
                score = None
                context = ""
                image = ""

                if isinstance(info, (tuple, list)):
                    if len(info) >= 3:
                        score = info[0]
                        context = info[1]
                        image = info[2]
                    elif len(info) == 2:
                        score = info[0]
                        context = info[1]

                candidate["score"] = score
                candidate["context_length"] = len(context or "")
                candidate["context_preview"] = (
                    (context or "")[:2000]
                )
                candidate["image"] = image

                row_fn = getattr(m, "_row_from_card", None)

                if callable(row_fn):
                    try:
                        # Current production API has image as the
                        # fourth argument, but support the older
                        # 3-argument shape too.
                        try:
                            card_row = row_fn(
                                url,
                                context,
                                q,
                                image,
                            )
                            candidate["row_call_shape"] = 4
                        except TypeError:
                            card_row = row_fn(
                                url,
                                context,
                                q,
                            )
                            candidate["row_call_shape"] = 3

                        candidate["row_from_card"] = {
                            "ok": True,
                            "returned": bool(card_row),
                            "row": card_row,
                        }

                    except Exception as exc:
                        candidate["row_from_card"] = {
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                else:
                    candidate["row_from_card"] = {
                        "ok": False,
                        "error": "function_not_found",
                    }

                target_candidates.append(candidate)

            out["discover"] = {
                "ok": True,
                "elapsed": round(
                    time.perf_counter() - started, 3
                ),
                "candidate_count": len(candidates or []),
                "target_found": bool(target_candidates),
                "target_candidates": target_candidates,
                "all_urls": [
                    item[0]
                    for item in (candidates or [])
                    if isinstance(item, (tuple, list))
                    and len(item) >= 1
                ],
            }

        except Exception as exc:
            out["discover"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        # ------------------------------------------------------------
        # 6. FINAL search()
        # ------------------------------------------------------------
        try:
            started = time.perf_counter()
            final_rows = m.search(q)

            final_rows = final_rows or []

            target_rows = [
                row
                for row in final_rows
                if isinstance(row, dict)
                and TARGET_ID in str(row.get("url", ""))
            ]

            out["final_search"] = {
                "ok": True,
                "elapsed": round(
                    time.perf_counter() - started, 3
                ),
                "count": len(final_rows),
                "target_found": bool(target_rows),
                "target_rows": target_rows,
            }

        except Exception as exc:
            out["final_search"] = {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

        # ------------------------------------------------------------
        # 7. SIMPLE DIAGNOSIS
        # ------------------------------------------------------------
        raw_found = bool(raw_target_urls)

        discover_found = bool(
            out.get("discover", {}).get("target_found")
        )

        parse_found = (
            out.get("parse_product", {}).get("row_count", 0) > 0
        )

        final_found = bool(
            out.get("final_search", {}).get("target_found")
        )

        card_found = False
        candidates = out.get("discover", {}).get(
            "target_candidates", []
        )

        for candidate in candidates:
            card = candidate.get("row_from_card", {})
            if card.get("returned"):
                card_found = True

        out["diagnosis"] = {
            "raw_html_contains_target": raw_found,
            "discover_contains_target": discover_found,
            "row_from_card_returns_target": card_found,
            "parse_product_returns_target": parse_found,
            "final_search_contains_target": final_found,
            "lost_between_raw_and_discover": (
                raw_found and not discover_found
            ),
            "lost_between_discover_and_card": (
                discover_found and not card_found
            ),
            "lost_between_card_and_parse": (
                discover_found
                and not card_found
                and parse_found
            ),
            "lost_after_parse_or_search": (
                parse_found and not final_found
            ),
        }

        return out

    except Exception as exc:
        out["ok"] = False
        out["error_type"] = type(exc).__name__
        out["error"] = str(exc)
        return out

from fastapi import APIRouter, Query
import time
import requests
from urllib.parse import urlparse

router = APIRouter()

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


@router.get("/diagnose-deloox-discovery-surfaces")
def diagnose_deloox_discovery_surfaces(q: str = Query("Hawas")):
    """
    READ-ONLY diagnostic.

    Compares Deloox discovery surfaces independently:
      1. every configured search endpoint
      2. every configured category endpoint
      3. sitemap discovery

    It never writes to the ScentHunter catalog, hydration queue, matcher,
    production search path, or resync state.
    """
    started = time.monotonic()
    query = str(q or "").strip() or "Hawas"

    out = {
        "diagnostic": "deloox-discovery-surfaces-read-only-v1",
        "ok": False,
        "store": "deloox",
        "query": query,
        "writes": False,
        "resync": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "catalog_written": False,
    }

    session = None

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from scrapers.deloox import scraper

        session = requests.Session()
        session.headers.update(getattr(scraper, "HEADERS", HEADERS))

        search_fn = getattr(scraper, "_search_endpoints", None)
        candidate_fn = getattr(scraper, "_candidate_product_urls", None)
        category_fn = getattr(scraper, "_category_pages", None)
        sitemap_fn = getattr(scraper, "_sitemap_product_urls", None)
        product_fn = getattr(scraper, "_product", None)

        missing = [
            name
            for name, fn in (
                ("_search_endpoints", search_fn),
                ("_candidate_product_urls", candidate_fn),
                ("_category_pages", category_fn),
                ("_sitemap_product_urls", sitemap_fn),
                ("_product", product_fn),
            )
            if not callable(fn)
        ]

        if missing:
            out["error"] = "missing_scraper_helpers:" + ",".join(missing)
            return out

        search_endpoints = list(search_fn(query))
        category_endpoints = list(category_fn())

        out["configured"] = {
            "search_endpoints": search_endpoints,
            "category_endpoints": category_endpoints,
        }

        def fetch(url):
            try:
                r = session.get(
                    url,
                    headers=getattr(scraper, "HEADERS", HEADERS),
                    timeout=getattr(scraper, "TIMEOUT", (3.5, 8.0)),
                    allow_redirects=True,
                )
                return {
                    "requested_url": url,
                    "final_url": r.url or url,
                    "status": r.status_code,
                    "text": r.text if r.status_code < 400 else "",
                    "error": None,
                }
            except Exception as exc:
                return {
                    "requested_url": url,
                    "final_url": url,
                    "status": None,
                    "text": "",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        def base_for(url):
            p = urlparse(url)
            return f"{p.scheme}://{p.netloc}"

        # ------------------------------------------------------------
        # SEARCH: unlike production _discover(), inspect ALL surfaces.
        # ------------------------------------------------------------
        search_results = []
        with ThreadPoolExecutor(
            max_workers=min(8, max(1, len(search_endpoints)))
        ) as pool:
            futures = [
                pool.submit(fetch, url)
                for url in search_endpoints
            ]
            for future in as_completed(futures):
                search_results.append(future.result())

        search_urls = set()
        search_details = []

        for item in search_results:
            found = []

            if item["text"]:
                try:
                    found = list(
                        candidate_fn(
                            item["text"],
                            query,
                            discovery_query=query,
                            accept_all_products=False,
                            base_url=base_for(item["final_url"]),
                        )
                        or []
                    )
                except Exception as exc:
                    item["candidate_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

            search_urls.update(found)

            search_details.append(
                {
                    "requested_url": item["requested_url"],
                    "final_url": item["final_url"],
                    "status": item["status"],
                    "candidate_count": len(found),
                    "candidates": found[:100],
                    "error": item.get("error"),
                    "candidate_error": item.get("candidate_error"),
                }
            )

        # ------------------------------------------------------------
        # CATEGORIES: inspect every configured category independently.
        # ------------------------------------------------------------
        category_results = []
        with ThreadPoolExecutor(
            max_workers=min(8, max(1, len(category_endpoints)))
        ) as pool:
            futures = [
                pool.submit(fetch, url)
                for url in category_endpoints
            ]
            for future in as_completed(futures):
                category_results.append(future.result())

        category_urls = set()
        category_details = []

        for item in category_results:
            found = []

            if item["text"]:
                try:
                    found = list(
                        candidate_fn(
                            item["text"],
                            query,
                            accept_all_products=True,
                            base_url=base_for(item["final_url"]),
                        )
                        or []
                    )
                except Exception as exc:
                    item["candidate_error"] = (
                        f"{type(exc).__name__}: {exc}"
                    )

            category_urls.update(found)

            category_details.append(
                {
                    "requested_url": item["requested_url"],
                    "final_url": item["final_url"],
                    "status": item["status"],
                    "candidate_count": len(found),
                    "candidates": found[:100],
                    "error": item.get("error"),
                    "candidate_error": item.get("candidate_error"),
                }
            )

        # ------------------------------------------------------------
        # SITEMAP: exact scraper helper, but only in memory.
        # ------------------------------------------------------------
        sitemap_urls = set()
        sitemap_error = None

        try:
            sitemap_urls = set(
                sitemap_fn(
                    session,
                    query,
                    max_sitemaps=48,
                    max_urls=80,
                )
                or []
            )
        except Exception as exc:
            sitemap_error = f"{type(exc).__name__}: {exc}"

        union_urls = sorted(
            search_urls | category_urls | sitemap_urls
        )

        # ------------------------------------------------------------
        # Validate the UNION through the retailer parser.
        # No ScentHunter persistence is touched.
        # ------------------------------------------------------------
        validated = []
        validation_errors = []

        for url in union_urls[:120]:
            try:
                item = fetch(url)

                if (
                    item["status"] is None
                    or item["status"] >= 400
                    or not item["text"]
                ):
                    continue

                parsed = product_fn(
                    item["final_url"],
                    item["text"],
                    query,
                )

                if not parsed:
                    continue

                validated.append(
                    {
                        "url": item["final_url"],
                        "name": parsed.get("name"),
                        "brand": (
                            parsed.get("source", {})
                            .get("source_brand")
                        ),
                        "size_ml": (
                            parsed.get("attributes", {})
                            .get("size_ml") or {}
                        ).get("value"),
                        "sku": (
                            parsed.get("identity", {})
                            .get("sku") or {}
                        ).get("value")
                        if isinstance(
                            parsed.get("identity", {}).get("sku"),
                            dict,
                        )
                        else None,
                        "price": (
                            parsed.get("offer", {})
                            .get("price")
                        ),
                        "sources": [
                            source
                            for source, urls in (
                                ("search", search_urls),
                                ("category", category_urls),
                                ("sitemap", sitemap_urls),
                            )
                            if item["final_url"] in urls
                            or url in urls
                        ],
                    }
                )

            except Exception as exc:
                validation_errors.append(
                    {
                        "url": url,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        # ------------------------------------------------------------
        # Explicit overlap math.
        # ------------------------------------------------------------
        search_only = search_urls - category_urls - sitemap_urls
        category_only = category_urls - search_urls - sitemap_urls
        sitemap_only = sitemap_urls - search_urls - category_urls
        search_category = search_urls & category_urls
        search_sitemap = search_urls & sitemap_urls
        category_sitemap = category_urls & sitemap_urls
        all_three = search_urls & category_urls & sitemap_urls

        out["search"] = {
            "surface_count": len(search_endpoints),
            "union_candidate_count": len(search_urls),
            "details": sorted(
                search_details,
                key=lambda x: (
                    x.get("status") is None,
                    x.get("status") or 999,
                    x["requested_url"],
                ),
            ),
        }

        out["categories"] = {
            "surface_count": len(category_endpoints),
            "union_candidate_count": len(category_urls),
            "details": sorted(
                category_details,
                key=lambda x: (
                    x.get("status") is None,
                    x.get("status") or 999,
                    x["requested_url"],
                ),
            ),
        }

        out["sitemap"] = {
            "candidate_count": len(sitemap_urls),
            "error": sitemap_error,
            "candidates": sorted(sitemap_urls)[:100],
        }

        out["union"] = {
            "candidate_count": len(union_urls),
            "search_only": len(search_only),
            "category_only": len(category_only),
            "sitemap_only": len(sitemap_only),
            "search_and_category": len(search_category),
            "search_and_sitemap": len(search_sitemap),
            "category_and_sitemap": len(category_sitemap),
            "all_three": len(all_three),
        }

        out["validated_count"] = len(validated)
        out["validated_products"] = validated
        out["validation_error_count"] = len(validation_errors)
        out["validation_errors"] = validation_errors[:20]

        # Diagnostic conclusion. This is descriptive, not a production decision.
        if len(validated) > 12:
            diagnosis = (
                "MORE_THAN_12_FOUND_OUTSIDE_PRIMARY_SEARCH"
            )
        elif len(validated) == 12:
            diagnosis = "ONLY_12_VALIDATED_ACROSS_ALL_SURFACES"
        else:
            diagnosis = "FEWER_THAN_12_VALIDATED_ACROSS_ALL_SURFACES"

        out["diagnosis"] = diagnosis
        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    finally:
        if session is not None:
            session.close()
        out["elapsed_sec"] = round(
            time.monotonic() - started,
            3,
        )

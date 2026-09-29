from fastapi import APIRouter, Query
import time
import requests

router = APIRouter()

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


@router.get("/diagnose-deloox-scraper")
def diagnose_deloox_scraper(q: str = Query("Liquid Brun")):
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"
    out = {
        "diagnostic": "deloox-scraper-discover-v2",
        "ok": False,
        "store": "Deloox",
        "query": query,
        "purpose": "direct read-only execution of deployed Deloox _discover(); real production discovery path, without ProductMatcher, catalog writes, hydration or resync",
    }
    session = None
    try:
        from scrapers.deloox import scraper
        discover = getattr(scraper, "_discover", None)
        if discover is None:
            out["error"] = "_discover not found in deployed Deloox scraper"
            return out
        out["scraper_module"] = getattr(scraper, "__file__", None)
        out["discover_function"] = getattr(discover, "__name__", None)
        out["category_function"] = getattr(getattr(scraper, "_discover_from_categories", None), "__name__", None)
        out["hierarchy_function"] = getattr(getattr(scraper, "_category_navigation_links", None), "__name__", None)
        session = requests.Session()
        session.headers.update(getattr(scraper, "HEADERS", HEADERS))
        candidates = discover(session, query)
        out["candidates"] = list(candidates or [])[:100]
        out["candidate_count"] = len(candidates or [])
        state = getattr(scraper, "_LAST_DISCOVERY_STATE", None)
        if isinstance(state, dict):
            out["discovery_state"] = dict(state)
        product_fn = getattr(scraper, "_product", None)
        validated = []
        validation_errors = []
        if product_fn:
            for url in (candidates or [])[:80]:
                try:
                    r = session.get(
                        url,
                        headers=getattr(scraper, "HEADERS", HEADERS),
                        timeout=getattr(scraper, "TIMEOUT", (3.5, 8.0)),
                        allow_redirects=True,
                    )
                    if r.status_code >= 400:
                        continue
                    item = product_fn(r.url or url, r.text, query)
                    if item:
                        validated.append(item)
                except Exception as exc:
                    validation_errors.append({
                        "url": url,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
        out["validated_products"] = validated
        out["validation_error_count"] = len(validation_errors)
        out["validation_errors"] = validation_errors[:20]
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        if session is not None:
            session.close()
        out["elapsed_sec"] = round(time.monotonic() - started, 3)


@router.get("/diagnose-deloox-catalog-discovery")
def diagnose_deloox_catalog_discovery():
    """
    READ-ONLY diagnostic of the actual catalog discovery function.

    This deliberately calls _discover_deloox_catalog() directly, but never
    calls discover_store(), _save_discovery(), hydration, ProductMatcher,
    production search, or any resync endpoint.
    """
    started = time.monotonic()
    out = {
        "diagnostic": "deloox-catalog-discovery-read-only-v1",
        "ok": False,
        "store": "Deloox",
        "query": "Liquid Brun",
        "purpose": (
            "direct read-only execution of deployed "
            "catalog_engine._discover_deloox_catalog(); "
            "no catalog writes, no hydration, no ProductMatcher, "
            "no production search, no resync"
        ),
    }

    try:
        import catalog_engine

        discover_fn = getattr(catalog_engine, "_discover_deloox_catalog", None)
        seeds_map = getattr(catalog_engine, "HTML_DISCOVERY_SEEDS", {})
        seeds = list((seeds_map.get("deloox") or ()))

        out["catalog_engine_module"] = getattr(catalog_engine, "__file__", None)
        out["discover_function"] = getattr(discover_fn, "__name__", None)
        out["configured_seed_count"] = len(seeds)
        out["configured_seeds"] = seeds

        if not callable(discover_fn):
            out["error"] = "_discover_deloox_catalog not found"
            return out

        hosts = []
        for seed in seeds:
            try:
                from urllib.parse import urlparse
                host = urlparse(seed).netloc.lower()
                if host and host not in hosts:
                    hosts.append(host)
            except Exception:
                pass
        out["seed_hosts"] = hosts

        deadline = time.time() + 30.0
        result = discover_fn(seeds, deadline=deadline)

        if not isinstance(result, dict):
            out["error"] = f"unexpected_result_type:{type(result).__name__}"
            return out

        product_urls = list((result.get("product_urls") or {}).keys())

        out["visited"] = result.get("visited")
        out["successes"] = result.get("successes")
        out["errors"] = list(result.get("errors") or [])[:20]
        out["product_count"] = len(product_urls)

        target_ids = {"1355229", "1385920"}
        matches = []
        for url in product_urls:
            if any(f"/{pid}/" in url for pid in target_ids):
                matches.append(url)

        out["target_product_urls_found"] = matches
        out["target_product_count"] = len(matches)
        out["target_1355229_found"] = any("1355229" in u for u in matches)
        out["target_1385920_found"] = any("1385920" in u for u in matches)

        if not matches:
            out["diagnosis"] = "CATALOG_DISCOVERY_DID_NOT_FIND_PROVEN_PRODUCT_URLS"
        else:
            out["diagnosis"] = "CATALOG_DISCOVERY_FOUND_PROVEN_PRODUCT_URLS"

        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)


@router.get("/catalog-gap-repair-deloox")
def catalog_gap_repair_deloox(q: str = Query(..., min_length=2)):
    """
    One-shot incremental catalog-gap repair.

    It uses the already-proven Deloox retailer discovery path for the supplied
    query, validates the returned product pages with Deloox's own _product()
    parser, then INSERTS ONLY NEW verified product URLs into the persistent
    catalog and hydration queue.

    It NEVER:
      - deactivates existing catalog URLs
      - replaces the Deloox catalog
      - runs discover_store()
      - runs a resync
      - calls ProductMatcher
      - calls production search
      - changes search behaviour

    This is an operational gap repair, not a request-time search fallback.
    """
    started = time.monotonic()
    query = str(q or "").strip()

    out = {
        "diagnostic": "deloox-catalog-gap-repair-v1",
        "ok": False,
        "store": "deloox",
        "query": query,
        "writes": False,
        "resync": False,
        "production_search_called": False,
        "product_matcher_called": False,
    }

    if len(query) < 2:
        out["error"] = "query_too_short"
        return out

    session = None

    try:
        from scrapers.deloox import scraper
        import catalog_engine

        discover = getattr(scraper, "_discover", None)
        product_fn = getattr(scraper, "_product", None)
        db_fn = getattr(catalog_engine, "db", None)
        url_slug_fn = getattr(catalog_engine, "url_slug", None)

        if not callable(discover):
            out["error"] = "deloox_discover_unavailable"
            return out
        if not callable(product_fn):
            out["error"] = "deloox_product_parser_unavailable"
            return out
        if not callable(db_fn):
            out["error"] = "catalog_db_unavailable"
            return out
        if not callable(url_slug_fn):
            out["error"] = "catalog_url_slug_unavailable"
            return out

        session = requests.Session()
        session.headers.update(getattr(scraper, "HEADERS", HEADERS))

        candidates = list(discover(session, query) or [])
        out["candidate_count"] = len(candidates)
        out["candidate_urls"] = candidates[:100]

        validated = []
        validation_errors = []

        for url in candidates[:80]:
            try:
                response = session.get(
                    url,
                    headers=getattr(scraper, "HEADERS", HEADERS),
                    timeout=getattr(scraper, "TIMEOUT", (3.5, 8.0)),
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    continue

                final_url = response.url or url
                item = product_fn(final_url, response.text, query)
                if not item:
                    continue

                validated.append({
                    "url": final_url,
                    "name": item.get("name"),
                    "brand": item.get("source", {}).get("source_brand"),
                    "size_ml": (item.get("attributes", {}).get("size_ml") or {}).get("value"),
                    "sku": (
                        item.get("identity", {}).get("sku") or {}
                    ).get("value")
                    if isinstance(item.get("identity", {}).get("sku"), dict)
                    else None,
                    "price": item.get("offer", {}).get("price"),
                })
            except Exception as exc:
                validation_errors.append({
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        out["validated_count"] = len(validated)
        out["validated_products"] = validated[:100]
        out["validation_error_count"] = len(validation_errors)
        out["validation_errors"] = validation_errors[:20]

        if not validated:
            out["diagnosis"] = "NO_VERIFIED_PRODUCTS_FROM_DELOOX_DISCOVERY"
            out["ok"] = True
            return out

        now = time.time()
        conn = db_fn()
        inserted = []
        already_present = []

        try:
            with conn:
                for item in validated:
                    url = item["url"]
                    existing = conn.execute(
                        "SELECT 1 FROM store_urls WHERE store=? AND url=?",
                        ("deloox", url),
                    ).fetchone()

                    if existing:
                        already_present.append(url)
                        continue

                    conn.execute(
                        """
                        INSERT INTO store_urls(
                            store,url,slug,lastmod,discovered_at,active
                        )
                        VALUES(?,?,?,?,?,1)
                        """,
                        (
                            "deloox",
                            url,
                            url_slug_fn(url),
                            "",
                            now,
                        ),
                    )

                    conn.execute(
                        """
                        INSERT INTO hydration_queue(
                            store,url,state,attempts,available_at,first_seen_at
                        )
                        VALUES(?,?,?,?,?,?)
                        ON CONFLICT(store,url) DO NOTHING
                        """,
                        (
                            "deloox",
                            url,
                            "PENDING",
                            0,
                            now,
                            now,
                        ),
                    )

                    inserted.append(url)
        finally:
            conn.close()

        out["writes"] = bool(inserted)
        out["inserted_count"] = len(inserted)
        out["inserted_urls"] = inserted[:100]
        out["already_present_count"] = len(already_present)
        out["already_present_urls"] = already_present[:100]
        out["diagnosis"] = (
            "CATALOG_GAP_REPAIRED_INCREMENTALLY"
            if inserted
            else "VERIFIED_PRODUCTS_ALREADY_IN_CATALOG"
        )
        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    finally:
        if session is not None:
            session.close()
        out["elapsed_sec"] = round(time.monotonic() - started, 3)

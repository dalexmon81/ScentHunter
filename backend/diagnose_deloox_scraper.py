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


@router.get("/diagnose-deloox-hydration-target")
def diagnose_deloox_hydration_target():
    """Hydrate only the two verified Liquid Brun Deloox URLs already in catalog.

    This is a targeted operational diagnostic: no discovery, no resync,
    no ProductMatcher and no production search. It uses catalog_engine's
    normal refresh_url() path and changes only the targeted queue/product rows.
    """
    started = time.monotonic()
    targets = [
        "https://www.deloox.be/produit/1355229/french-avenue-liquid-brun-eau-de-parfum-100-ml.html",
        "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html",
    ]
    out = {
        "diagnostic": "deloox-hydration-target-v1",
        "ok": False,
        "store": "deloox",
        "resync": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "targets": targets,
        "results": [],
    }

    try:
        import uuid
        import catalog_engine

        db_fn = getattr(catalog_engine, "db", None)
        refresh_url = getattr(catalog_engine, "refresh_url", None)
        if not callable(db_fn) or not callable(refresh_url):
            out["error"] = "catalog_hydration_functions_unavailable"
            return out

        for url in targets:
            token = uuid.uuid4().hex
            conn = db_fn()
            claimed = False
            try:
                with conn:
                    row = conn.execute(
                        "SELECT state, attempts FROM hydration_queue WHERE store=? AND url=?",
                        ("deloox", url),
                    ).fetchone()
                    if not row:
                        out["results"].append({"url": url, "status": "NOT_IN_QUEUE"})
                        continue

                    previous_state = str(row["state"] or "")
                    if previous_state == "DONE":
                        out["results"].append({"url": url, "status": "ALREADY_DONE"})
                        continue

                    updated = conn.execute(
                        """
                        UPDATE hydration_queue
                        SET state='PROCESSING', lease_token=?, leased_until=?,
                            last_started_at=?, attempts=COALESCE(attempts,0)+1
                        WHERE store=? AND url=? AND state IN ('PENDING','ERROR')
                        """,
                        (token, time.time() + 180, time.time(), "deloox", url),
                    ).rowcount
                    claimed = updated == 1
            finally:
                conn.close()

            if not claimed:
                out["results"].append({
                    "url": url,
                    "status": "NOT_CLAIMED",
                    "reason": "queue row is currently PROCESSING or another non-claimable state",
                })
                continue

            try:
                item = refresh_url("deloox", url)
                if item and item.get("name"):
                    conn = db_fn()
                    try:
                        with conn:
                            conn.execute(
                                """
                                UPDATE hydration_queue
                                SET state='DONE', leased_until=NULL, lease_token=NULL,
                                    last_finished_at=?, last_error=NULL, last_http_status=NULL
                                WHERE store=? AND url=? AND lease_token=? AND state='PROCESSING'
                                """,
                                (time.time(), "deloox", url, token),
                            )
                    finally:
                        conn.close()
                    out["results"].append({
                        "url": url,
                        "status": "DONE",
                        "name": item.get("name"),
                        "brand": item.get("brand"),
                        "size_ml": item.get("size_ml"),
                    })
                else:
                    conn = db_fn()
                    try:
                        row = conn.execute(
                            "SELECT fetch_status FROM store_products WHERE store=? AND url=?",
                            ("deloox", url),
                        ).fetchone()
                        detail = str(row["fetch_status"]) if row and row["fetch_status"] else "product_parser_not_found"
                        with conn:
                            conn.execute(
                                """
                                UPDATE hydration_queue
                                SET state='ERROR', available_at=?, leased_until=NULL,
                                    lease_token=NULL, last_finished_at=?, last_error=?
                                WHERE store=? AND url=? AND lease_token=? AND state='PROCESSING'
                                """,
                                (time.time() + 60, time.time(), detail[:1000], "deloox", url, token),
                            )
                    finally:
                        conn.close()
                    out["results"].append({"url": url, "status": "ERROR", "detail": detail})
            except Exception as exc:
                conn = db_fn()
                try:
                    with conn:
                        conn.execute(
                            """
                            UPDATE hydration_queue
                            SET state='ERROR', available_at=?, leased_until=NULL,
                                lease_token=NULL, last_finished_at=?, last_error=?
                            WHERE store=? AND url=? AND lease_token=? AND state='PROCESSING'
                            """,
                            (time.time() + 60, time.time(), f"{type(exc).__name__}: {exc}"[:1000], "deloox", url, token),
                        )
                finally:
                    conn.close()
                out["results"].append({
                    "url": url,
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        out["ok"] = True
        out["diagnosis"] = "TARGETED_DELOOX_HYDRATION_EXECUTED"
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)


@router.get("/diagnose-catalog-search-pipeline")
def diagnose_catalog_search_pipeline(q: str = Query("Liquid Brun")):
    """READ-ONLY trace of catalog search -> clean_result -> ProductMatcher."""
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"
    out = {"diagnostic":"catalog-search-pipeline-read-only-v1","ok":False,"query":query,"production_search_called":False,"resync":False,"writes":False,"stores":{}}
    try:
        import catalog_engine
        import main as main_module
        search_local = getattr(catalog_engine, "search_local", None)
        clean_result_fn = getattr(main_module, "clean_result", None)
        resolve_fn = getattr(main_module, "_resolve_offer_identity", None)
        terms_fn = getattr(main_module, "_catalog_search_terms", None)
        if not callable(search_local) or not callable(clean_result_fn) or not callable(resolve_fn):
            out["error"]="required_pipeline_functions_unavailable"; return out
        terms = list(terms_fn(query) or []) if callable(terms_fn) else []
        if not terms: terms=[query]
        candidate_limit=min(128,max(64,len(terms)*2)) if len(terms)>1 else 64
        raw_rows=list(search_local(query,per_store=candidate_limit,search_terms=terms) or [])
        out.update({"search_terms":terms,"candidate_limit":candidate_limit,"catalog_search_row_count":len(raw_rows)})
        for store in ("deloox","sabina"):
            out["stores"][store]={"catalog_rows":[],"clean_rows":[],"matched_rows":[],"rejected_rows":[],"unresolved_rows":[]}
        for index,raw in enumerate(raw_rows):
            if not isinstance(raw,dict): continue
            store_key=str(raw.get("store_key") or raw.get("store") or raw.get("shop") or "").strip().lower()
            if store_key not in out["stores"]: continue
            compact={"index":index,"url":raw.get("url") or raw.get("product_url"),"name":raw.get("name"),"brand":raw.get("brand"),"size_ml":raw.get("size_ml"),"fetch_status":raw.get("fetch_status"),"_needs_refresh":raw.get("_needs_refresh"),"price":raw.get("price"),"availability":raw.get("availability")}
            out["stores"][store_key]["catalog_rows"].append(compact)
            try: prepared=clean_result_fn(raw,store_key)
            except Exception as exc:
                out["stores"][store_key]["clean_rows"].append({**compact,"clean_error":f"{type(exc).__name__}: {exc}"}); continue
            if not isinstance(prepared,dict):
                out["stores"][store_key]["clean_rows"].append({**compact,"clean_result":None}); continue
            clean={"url":prepared.get("url") or prepared.get("product_url"),"name":prepared.get("name"),"brand":prepared.get("brand"),"_raw_name":prepared.get("_raw_name"),"_raw_brand":prepared.get("_raw_brand"),"size_ml":prepared.get("size_ml"),"price":prepared.get("price"),"availability":prepared.get("availability")}
            out["stores"][store_key]["clean_rows"].append(clean)
            try: resolved=resolve_fn(prepared,query)
            except Exception as exc:
                out["stores"][store_key]["unresolved_rows"].append({**clean,"resolve_error":f"{type(exc).__name__}: {exc}"}); continue
            if not isinstance(resolved,dict):
                out["stores"][store_key]["unresolved_rows"].append({**clean,"resolve_result":None}); continue
            match={"url":resolved.get("url") or resolved.get("product_url"),"name":resolved.get("name") or resolved.get("title"),"brand":resolved.get("brand"),"size_ml":resolved.get("size_ml"),"match_status":resolved.get("_match_status"),"reject_reason":resolved.get("_reject_reason"),"match_method":resolved.get("match_method"),"match_score":resolved.get("match_score"),"catalog_id":resolved.get("catalog_id"),"canonical_name":resolved.get("canonical_name"),"canonical_brand":resolved.get("canonical_brand"),"match_error":resolved.get("_match_error")}
            if resolved.get("_match_status")=="matched" and resolved.get("catalog_id"): out["stores"][store_key]["matched_rows"].append(match)
            elif resolved.get("_match_status")=="rejected": out["stores"][store_key]["rejected_rows"].append(match)
            else: out["stores"][store_key]["unresolved_rows"].append(match)
        for store,data in out["stores"].items():
            for k in ("catalog_rows","clean_rows","matched_rows","rejected_rows","unresolved_rows"): data[k.replace("_rows","_count")]=len(data[k])
        out["ok"]=True
        out["diagnosis"]="PIPELINE_REACHED_MATCHER" if any(out["stores"][s]["matched_count"] for s in out["stores"]) else "PIPELINE_LOST_ROWS_BEFORE_MATCHER_OR_MATCHER_REJECTED"
        return out
    except Exception as exc:
        out["error"]=f"{type(exc).__name__}: {exc}"; return out
    finally: out["elapsed_sec"]=round(time.monotonic()-started,3)



@router.get("/diagnose-deloox-search-pagination")
def diagnose_deloox_search_pagination(q: str = Query("Hawas")):
    """Read-only proof of Deloox search pagination versus deployed _discover().

    This endpoint never writes to SQLite, hydration_queue or store_urls and
    never calls production search, ProductMatcher or any repair/resync path.
    It fetches the first three public Deloox .be search pages explicitly and
    compares their product URLs with the URLs returned by scraper._discover().
    """
    started = time.monotonic()
    query = str(q or "").strip() or "Hawas"
    base_surface = "https://www.deloox.be/chercher.html"
    out = {
        "diagnostic": "deloox-search-pagination-v2",
        "ok": False,
        "store": "Deloox",
        "query": query,
        "purpose": "read-only proof of whether Deloox search pagination exposes additional product URLs that deployed _discover() does not return",
        "writes": False,
        "resync": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "catalog_written": False,
        "base_surface": base_surface,
        "pages": [],
        "discover": {},
    }

    session = None
    try:
        from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
        from scrapers.deloox import scraper

        candidate_fn = getattr(scraper, "_candidate_product_urls", None)
        discover_fn = getattr(scraper, "_discover", None)
        headers = getattr(scraper, "HEADERS", HEADERS)
        timeout = getattr(scraper, "TIMEOUT", (3.5, 8.0))

        if not callable(candidate_fn):
            out["error"] = "deloox_candidate_product_urls_unavailable"
            return out
        if not callable(discover_fn):
            out["error"] = "deloox_discover_unavailable"
            return out

        session = requests.Session()
        session.headers.update(headers)

        def set_query(url, page=None, query_value=None):
            parsed = urlparse(url)
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            filtered = [(k, v) for k, v in pairs if k.lower() not in {"q", "page", "pagina", "p"}]
            filtered.append(("q", query if query_value is None else query_value))
            if page is not None:
                filtered.append(("page", str(page)))
            return urlunparse(parsed._replace(query=urlencode(filtered, doseq=True)))

        page1_url = set_query(base_surface, page=None)
        page1_response = session.get(
            page1_url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )

        if page1_response.status_code >= 400:
            out["error"] = f"page1_http_{page1_response.status_code}"
            out["pages"] = [{"page": 1, "requested_url": page1_url, "status": page1_response.status_code}]
            return out

        # Prefer retailer-provided pagination links (they may carry the CSRF
        # token/session parameters), then fall back to explicit page=N URLs.
        pagination_links = {}
        soup = __import__("bs4").BeautifulSoup(page1_response.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page1_response.url, href)
            parsed = urlparse(absolute)
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            page_value = params.get("page") or params.get("pagina") or params.get("p")
            if page_value in {"2", "3"}:
                pagination_links[int(page_value)] = absolute

        pages_to_fetch = {
            1: page1_response.url,
            2: pagination_links.get(2) or set_query(page1_response.url, 2),
            3: pagination_links.get(3) or set_query(page1_response.url, 3),
        }

        all_page_urls = {}
        all_product_urls = []
        seen_products = set()

        def inspect_page(number, requested_url, response, query_value=None, fallback=False):
            final_url = response.url or requested_url
            found = list(candidate_fn(
                response.text,
                query if query_value is None else query_value,
                discovery_query=query if query_value is None else query_value,
                accept_all_products=True,
                base_url=f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}",
            ) or [])
            unique = []
            for url in found:
                if url not in unique:
                    unique.append(url)
                if url not in seen_products:
                    seen_products.add(url)
                    all_product_urls.append(url)
            all_page_urls[number] = unique
            return {
                "page": number,
                "requested_url": requested_url,
                "final_url": final_url,
                "status": response.status_code,
                "bytes": len(response.content or b""),
                "product_url_count": len(unique),
                "product_urls": unique,
                "pagination_link_found": number in pagination_links,
                "fallback": fallback,
            }

        page1_info = inspect_page(1, page1_url, page1_response)
        out["pages"].append(page1_info)

        for number in (2, 3):
            requested = pages_to_fetch[number]
            try:
                response = session.get(
                    requested,
                    headers=headers,
                    timeout=timeout,
                    allow_redirects=True,
                )
                if response.status_code < 400:
                    out["pages"].append(inspect_page(number, requested, response))
                else:
                    out["pages"].append({
                        "page": number,
                        "requested_url": requested,
                        "final_url": response.url or requested,
                        "status": response.status_code,
                        "bytes": len(response.content or b""),
                        "product_url_count": 0,
                        "product_urls": [],
                        "pagination_link_found": number in pagination_links,
                        "fallback": False,
                    })
            except requests.RequestException as exc:
                out["pages"].append({
                    "page": number,
                    "requested_url": requested,
                    "status": None,
                    "product_url_count": 0,
                    "product_urls": [],
                    "pagination_link_found": number in pagination_links,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        # Deloox can expose the final page with a harmless trailing space in q
        # (e.g. Hawas+). If explicit page=3 produced no products, test that
        # store-generated form once; this remains generic and read-only.
        page3_info = next((x for x in out["pages"] if x.get("page") == 3), None)
        if page3_info and page3_info.get("product_url_count", 0) == 0:
            fallback_url = set_query(page1_response.url, 3, query + " ")
            if fallback_url != page3_info.get("requested_url"):
                try:
                    response = session.get(
                        fallback_url,
                        headers=headers,
                        timeout=timeout,
                        allow_redirects=True,
                    )
                    if response.status_code < 400:
                        fallback_info = inspect_page(3, fallback_url, response, query_value=query + " ", fallback=True)
                        fallback_info["reason"] = "page3_empty_primary_url"
                        out["pages"].append(fallback_info)
                except requests.RequestException as exc:
                    out["pages"].append({
                        "page": 3,
                        "requested_url": fallback_url,
                        "status": None,
                        "product_url_count": 0,
                        "product_urls": [],
                        "fallback": True,
                        "error": f"{type(exc).__name__}: {exc}",
                    })

        # Execute the exact deployed discovery path once, after the direct page
        # inspection. This is read-only and is the critical comparison point.
        discover_candidates = list(discover_fn(session, query) or [])
        discover_set = set(discover_candidates)
        page_union = list(all_product_urls)
        missing = [url for url in page_union if url not in discover_set]

        out["page_product_total"] = sum(
            len(x.get("product_urls", [])) for x in out["pages"]
        )
        out["unique_product_urls_pages_1_to_3"] = len(page_union)
        out["page_product_urls"] = page_union
        out["discover"] = {
            "candidate_count": len(discover_candidates),
            "candidate_urls": discover_candidates,
            "missing_from_deployed_discover_count": len(missing),
            "missing_from_deployed_discover": missing,
        }

        if missing:
            out["diagnosis"] = "PAGINATION_NOT_FOLLOWED_BY_DISCOVER"
        elif len(page_union) > len(discover_candidates):
            out["diagnosis"] = "PAGINATION_PRODUCES_MORE_URLS_THAN_DISCOVER"
        else:
            out["diagnosis"] = "NO_PAGINATION_GAP_PROVEN"

        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        if session is not None:
            session.close()
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

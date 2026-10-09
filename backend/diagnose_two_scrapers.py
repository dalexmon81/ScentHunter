from fastapi import APIRouter, Query
import concurrent.futures
import re
import time
from urllib.parse import quote, urljoin

import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}
TOKEN_RE = re.compile(r"\b(liquid|brun)\b", re.I)


def _get(url, timeout=(1.5, 5.0), headers=None):
    t = time.monotonic()
    try:
        r = requests.get(
            url,
            headers=headers or HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        return {
            "ok": True,
            "status": r.status_code,
            "url": r.url,
            "elapsed_sec": round(time.monotonic() - t, 3),
            "bytes": len(r.content),
            "text": r.text,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic() - t, 3),
            "bytes": 0,
            "text": "",
            "error": f"{type(e).__name__}: {e}",
        }


def _compact(s, n=500):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n]


@router.get('/diagnose-html-discovery-trace')
def diagnose_html_discovery_trace_endpoint(
    store: str = Query('deloox'),
    q: str = Query('Liquid Brun'),
    max_pages: int = Query(120, ge=1, le=800),
    max_depth: int = Query(8, ge=0, le=8),
    max_events: int = Query(500, ge=50, le=2000),
):
    try:
        from catalog_engine import diagnose_html_discovery_trace
        return diagnose_html_discovery_trace(store=store, query=q, max_pages=max_pages,
                                             max_depth=max_depth, max_events=max_events)
    except Exception as exc:
        return {'ok': False, 'diagnostic': 'html-discovery-trace-read-only-v1',
                'error': f'{type(exc).__name__}: {exc}', 'store': store, 'query': q}


@router.get("/diagnose-sabina-catalog")
def diagnose_sabina_precise(q: str = Query("Liquid Brun")):
    base = "https://www.sabina.com"
    urls = [
        f"{base}/it/ricerca_old?s={quote(q)}",
        f"{base}/it/ricerca?search_query={quote(q)}",
        f"{base}/it/ricerca_old?search_query={quote(q)}",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u), urls))

    probes = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        hits = {}
        for marker in [
            q,
            "liquid brun",
            "liquid-brun",
            "34982",
            "720100",
            "french avenue",
            "profumi-da-uomo",
            "/it/profumi-da-uomo/",
        ]:
            i = low.find(marker.lower())
            hits[marker] = None if i < 0 else {
                "offset": i,
                "context": _compact(text[max(0, i - 350):i + 700], 1050),
            }

        links = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
            href = m.group(1)
            if any(
                x in href.lower()
                for x in ["34982", "liquid", "brun", "profumi-da-uomo"]
            ):
                links.append(urljoin(p["url"], href))
        probes.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "markers": hits,
            "matching_links": list(dict.fromkeys(links))[:50],
        })

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "purpose": "read-only inspection of real search responses; no production search() and no product-specific rule",
        "probes": probes,
    }


@router.get("/diagnose-deloox-catalog")
def diagnose_deloox_precise(q: str = Query("Liquid Brun")):
    urls = [
        "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html",
        "https://www.deloox.com/en/category/1121322/french-avenue-fragrances.html",
        "https://www.deloox.com/en/category/1132834/liquid-brun.html",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(
            ex.map(
                lambda u: _get(
                    u,
                    headers={
                        "User-Agent": UA,
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                ),
                urls,
            )
        )

    out = []
    for p in pages:
        text = p["text"]
        matches = []
        for m in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            text,
            re.I | re.S,
        ):
            href, inner = m.group(1), m.group(2)
            visible = re.sub(r"<[^>]+>", " ", inner)
            visible = _compact(visible, 800)
            if TOKEN_RE.search(visible):
                matches.append({
                    "url": urljoin(p["url"], href),
                    "text": visible,
                })
        raw_contexts = []
        for m in list(TOKEN_RE.finditer(text))[:20]:
            raw_contexts.append(
                _compact(text[max(0, m.start() - 300):m.end() + 500], 900)
            )
        out.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "card_token_hits": matches[:50],
            "raw_token_contexts": raw_contexts,
        })

    return {
        "diagnostic": True,
        "store": "Deloox",
        "query": q,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "purpose": "read-only inspection of category/card text; no URL-token discovery and no production search()",
        "pages": out,
    }


@router.get("/diagnose-sabina-discovery-trace")
def diagnose_sabina_discovery_trace(q: str = Query("9 PM")):
    """Deep read-only trace of Sabina discovery stages."""
    started = time.monotonic()
    out = {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "purpose": "read-only trace of deployed Sabina discovery stages",
    }
    try:
        from scrapers.sabina import scraper
        session = requests.Session()
        try:
            out["scraper_module"] = getattr(scraper, "__file__", None)
            trace = {}
            search_url = f"{scraper.SEARCH_URL}?search_query={quote(q)}"
            page = _get(
                search_url,
                timeout=(2, 8),
                headers=getattr(scraper, "HEADERS", HEADERS),
            )
            trace["search_page"] = {
                k: page[k]
                for k in ("ok", "status", "url", "elapsed_sec", "bytes", "error")
            }
            text = page["text"]
            links = []
            if text:
                for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
                    u = urljoin(page["url"], m.group(1))
                    if scraper.is_product_url(u):
                        links.append(u)
            trace["search_product_urls"] = list(dict.fromkeys(links))[:100]

            robots_url = scraper.BASE_URL + "/robots.txt"
            robots = _get(
                robots_url,
                timeout=(2, 8),
                headers=getattr(scraper, "HEADERS", HEADERS),
            )
            trace["robots"] = {
                k: robots[k]
                for k in ("ok", "status", "url", "elapsed_sec", "bytes", "error")
            }
            sitemap_refs = re.findall(
                r"(?im)^\s*Sitemap:\s*(https?://\S+)",
                robots["text"] or "",
            )
            trace["robots_sitemaps"] = sitemap_refs[:100]

            sitemap_http_trace = []
            for sitemap_url in sitemap_refs[:20]:
                sp = _get(
                    sitemap_url,
                    timeout=(2, 12),
                    headers=getattr(scraper, "HEADERS", HEADERS),
                )
                body = sp["text"] or ""
                locs = re.findall(
                    r"<\s*loc(?:\s[^>]*)?>\s*(.*?)\s*</\s*loc\s*>",
                    body,
                    re.I | re.S,
                )
                sitemap_http_trace.append({
                    "url": sitemap_url,
                    "ok": sp["ok"],
                    "status": sp["status"],
                    "elapsed_sec": sp["elapsed_sec"],
                    "bytes": sp["bytes"],
                    "error": sp["error"],
                    "loc_count": len(locs),
                    "loc_sample": [
                        re.sub(r"\s+", " ", x).strip() for x in locs[:20]
                    ],
                    "head": re.sub(r"\s+", " ", body[:1500]).strip(),
                })
            trace["sitemap_http_trace"] = sitemap_http_trace

            sitemap_fn = getattr(scraper, "_discover_from_sitemaps", None)
            if sitemap_fn:
                try:
                    result = sitemap_fn(session, q)
                    trace["sitemap_discovery"] = {
                        "ok": True,
                        "count": len(result or []),
                        "urls": (result or [])[:100],
                    }
                except Exception as exc:
                    trace["sitemap_discovery"] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
            else:
                trace["sitemap_discovery"] = {
                    "ok": False,
                    "error": "_discover_from_sitemaps not found",
                }

            score_fn = getattr(scraper, "_catalog_candidate_score", None)
            candidates = []
            if score_fn and trace.get("sitemap_discovery", {}).get("ok"):
                for u in trace["sitemap_discovery"]["urls"]:
                    try:
                        candidates.append({"url": u, "score": score_fn(u, q)})
                    except Exception as exc:
                        candidates.append({
                            "url": u,
                            "score_error": f"{type(exc).__name__}: {exc}",
                        })
            trace["sitemap_scored_candidates"] = sorted(
                candidates,
                key=lambda x: x.get("score", -1),
                reverse=True,
            )[:100]

            final = scraper.discover_product_urls(session, q)
            trace["final_discovery"] = {
                "count": len(final or []),
                "urls": (final or [])[:100],
            }
            out["trace"] = trace
        finally:
            session.close()
        out["elapsed_sec"] = round(time.monotonic() - started, 3)
        return out
    except Exception as exc:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


@router.get("/diagnose-discovery-trace")
def diagnose_discovery_trace(
    q: str = Query("Liquid Brun"),
    max_sitemaps: int = Query(1000, ge=1, le=5000),
    max_samples: int = Query(30, ge=1, le=200),
):
    """Read-only replay of catalog_engine discovery decisions for Sabina/Deloox.

    This endpoint intentionally does not execute the HTML crawl. It replays the
    sitemap phase in memory and reports the exact condition under which the
    CURRENT catalog_engine.py would enter the HTML fallback, including the
    configured threshold. This keeps the diagnostic fast and prevents a
    diagnostic request from accidentally becoming a production discovery job.
    """
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"
    result = {
        "diagnostic": "generic-discovery-trace-v3",
        "ok": True,
        "query": query,
        "purpose": (
            "read-only replay of catalog_engine sitemap discovery and the "
            "current HTML-fallback decision; no DB writes, no production "
            "search, no hydration, no ProductMatcher, no HTML crawl"
        ),
        "stores": {},
    }

    try:
        import catalog_engine as ce

        wanted = set(ce.tokens(query))
        fallback_threshold = int(
            getattr(ce, "HTML_FALLBACK_SITEMAP_PRODUCT_THRESHOLD", 0) or 0
        )

        for store in ("sabina", "deloox"):
            store_started = time.monotonic()
            try:
                roots, robots_diag = ce._seed_sitemaps(store)
            except Exception as exc:
                result["stores"][store] = {
                    "ok": False,
                    "stage": "seed_sitemaps",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_sec": round(time.monotonic() - store_started, 3),
                }
                continue

            queue = [(url, 0) for url in roots]
            queued = set(roots)
            visited = set()
            product_urls = set()
            query_hits = []
            product_samples = []
            sitemap_errors = []
            sitemap_successes = 0
            xml_entries = 0
            sitemap_index_entries = 0
            product_entries = 0
            query_token_hits = {token: 0 for token in sorted(wanted)}
            effective_limit = min(max_sitemaps, ce.MAX_SITEMAPS_PER_STORE)

            while (
                queue
                and len(visited) < effective_limit
                and len(product_urls) < ce.MAX_TOTAL_DISCOVERED_URLS
                and (time.monotonic() - store_started) < ce.DISCOVERY_HARD_TIMEOUT
            ):
                batch = []
                while queue and len(batch) < ce.SYNC_WORKERS * 4:
                    sm, depth = queue.pop(0)
                    if sm in visited:
                        continue
                    visited.add(sm)
                    batch.append((sm, depth))
                if not batch:
                    continue

                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=min(ce.SYNC_WORKERS, len(batch))
                ) as pool:
                    futures = {
                        pool.submit(ce._fetch_sitemap, store, sm): (sm, depth)
                        for sm, depth in batch
                    }
                    for future in concurrent.futures.as_completed(futures):
                        sm, depth = futures[future]
                        try:
                            _source, final, entries, error = future.result()
                        except Exception as exc:
                            final, entries = sm, []
                            error = f"EXCEPTION:{type(exc).__name__}:{exc}"

                        if error:
                            sitemap_errors.append({
                                "sitemap": sm,
                                "depth": depth,
                                "error": error,
                            })
                            continue

                        sitemap_successes += 1
                        xml_entries += len(entries)

                        for kind, raw_url, lastmod in entries:
                            absolute = (
                                urljoin(final or sm, raw_url.strip())
                                if raw_url else ""
                            )
                            if not absolute:
                                continue

                            if kind == "sitemap":
                                sitemap_index_entries += 1
                                if (
                                    depth + 1 <= ce.MAX_SITEMAP_DEPTH
                                    and absolute not in queued
                                    and len(visited) + len(queue) < effective_limit
                                ):
                                    queued.add(absolute)
                                    queue.append((absolute, depth + 1))
                                continue

                            if not ce._looks_product(absolute):
                                continue

                            product_urls.add(absolute)
                            product_entries += 1

                            if len(product_samples) < max_samples:
                                product_samples.append(absolute)

                            normalized_url = set(ce.tokens(absolute))
                            if wanted and wanted.issubset(normalized_url):
                                if len(query_hits) < max_samples:
                                    query_hits.append(absolute)

                            for token in wanted:
                                if token in normalized_url:
                                    query_token_hits[token] += 1

            reached_limit = len(visited) >= effective_limit
            timed_out = (
                time.monotonic() - store_started
            ) >= ce.DISCOVERY_HARD_TIMEOUT

            sitemap_count = len(product_urls)

            if fallback_threshold > 0:
                fallback_runs = sitemap_count < fallback_threshold
                fallback_rule = (
                    f"RUNS when sitemap product URL count ({sitemap_count}) "
                    f"is below HTML_FALLBACK_SITEMAP_PRODUCT_THRESHOLD "
                    f"({fallback_threshold})"
                )
                fallback_status = (
                    "RUNS_BELOW_THRESHOLD"
                    if fallback_runs
                    else "SKIPPED_ABOVE_THRESHOLD"
                )
            else:
                fallback_runs = sitemap_count == 0
                fallback_rule = (
                    "RUNS only when sitemap product URL count is zero "
                    "(deployed catalog_engine has no threshold constant)"
                )
                fallback_status = (
                    "RUNS_ZERO_SITEMAP_PRODUCTS"
                    if fallback_runs
                    else "SKIPPED_NONZERO_SITEMAP_PRODUCTS"
                )

            seeds = getattr(ce, "HTML_DISCOVERY_SEEDS", {})
            store_seeds = list(seeds.get(store, ()) or ())

            result["stores"][store] = {
                "ok": True,
                "roots_found": len(roots),
                "robots_diagnostics": robots_diag[:20],
                "sitemaps_visited": len(visited),
                "sitemaps_successful": sitemap_successes,
                "sitemap_errors": len(sitemap_errors),
                "sitemap_error_samples": sitemap_errors[:max_samples],
                "xml_entries_seen": xml_entries,
                "sitemap_index_entries": sitemap_index_entries,
                "product_urls_seen": sitemap_count,
                "product_entries_seen": product_entries,
                "query_tokens": sorted(wanted),
                "query_url_hits": len(query_hits),
                "query_url_hit_samples": query_hits[:max_samples],
                "query_token_hit_counts": query_token_hits,
                "product_url_samples": product_samples[:max_samples],
                "html_fallback": {
                    "threshold": fallback_threshold,
                    "seed_count": len(store_seeds),
                    "seeds": store_seeds[:20],
                    "decision": fallback_status,
                    "rule": fallback_rule,
                    "would_execute_in_production_discovery": fallback_runs,
                    "note": (
                        "This diagnostic reports the decision only; it does "
                        "not execute the HTML crawl or write its results."
                    ),
                },
                "replay_limits": {
                    "requested_max_sitemaps": max_sitemaps,
                    "effective_max_sitemaps": effective_limit,
                    "reached_sitemap_limit": reached_limit,
                    "timed_out": timed_out,
                },
                "elapsed_sec": round(time.monotonic() - store_started, 3),
            }

    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"

    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result


# ============================================================================
# FAST CATALOG-FIRST DIAGNOSTIC
# ============================================================================
# This endpoint is deliberately read-only and deliberately does NOT call
# main.py, search_local(), ProductMatcher, URL discovery, hydration, or cache
# invalidation. It reads only SQLite and tells us whether the requested tokens
# are already present in the active Sabina/Deloox catalog.

TARGET_STORES = ("sabina", "deloox")


def _catalog_token_set(value):
    try:
        from catalog_engine import norm
        return set(norm(str(value or "")).split())
    except Exception:
        return set(
            re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split()
        )


def _catalog_tokens(value):
    try:
        from catalog_engine import tokens
        return tuple(tokens(str(value or "")))
    except Exception:
        return tuple(_catalog_token_set(value))


def _catalog_row_tokens(row):
    text = " ".join(
        str(row[key] or "")
        for key in ("slug", "product_name", "product_brand")
    )
    return _catalog_token_set(text)


def _catalog_compact_row(row):
    return {
        "url": row["url"],
        "slug": row["slug"],
        "name": row["product_name"],
        "brand": row["product_brand"],
        "fetch_status": row["fetch_status"],
        "fetched_at": row["fetched_at"],
        "lastmod": row["lastmod"],
        "discovered_at": row["discovered_at"],
    }


def _catalog_rows(conn, store):
    return conn.execute(
        """SELECT
               u.url,
               u.slug,
               u.lastmod,
               u.discovered_at,
               p.name AS product_name,
               p.brand AS product_brand,
               p.fetch_status,
               p.fetched_at
           FROM store_urls u
           LEFT JOIN store_products p
             ON p.store=u.store
            AND p.url=u.url
           WHERE u.store=? AND u.active=1
           ORDER BY u.url""",
        (store,),
    ).fetchall()


def _catalog_queue_state(conn, store, urls):
    if not urls:
        return {}
    placeholders = ",".join("?" for _ in urls)
    rows = conn.execute(
        f"""SELECT store,url,state,attempts,last_error,last_http_status,
                    last_started_at,last_finished_at,available_at
             FROM hydration_queue
             WHERE store=? AND url IN ({placeholders})""",
        (store, *urls),
    ).fetchall()
    return {row["url"]: dict(row) for row in rows}


@router.get("/diagnose-catalog-store")
def diagnose_catalog_store(
    store: str = Query("parfumzentrum"),
    q: str = Query("Rayhaan"),
    max_candidates: int = Query(100, ge=1, le=500),
):
    """Generic, strictly read-only inspection of one active catalog store.

    This endpoint isolates the catalog layer only. It never calls the
    production search pipeline, a scraper, ProductMatcher, discovery,
    hydration, or any write operation.
    """
    started = time.monotonic()
    store_key = str(store or "").strip().lower()
    query = str(q or "").strip()

    try:
        from catalog_engine import STORES, db

        if store_key not in tuple(STORES):
            return {
                "diagnostic": "catalog-store-read-only-v1",
                "ok": False,
                "production_search_called": False,
                "product_matcher_called": False,
                "scraper_called": False,
                "database_written": False,
                "store": store_key,
                "query": query,
                "error": (
                    "invalid_store: available stores="
                    + ",".join(str(item) for item in STORES)
                ),
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        if not query:
            return {
                "diagnostic": "catalog-store-read-only-v1",
                "ok": False,
                "production_search_called": False,
                "product_matcher_called": False,
                "scraper_called": False,
                "database_written": False,
                "store": store_key,
                "query": query,
                "error": "empty_query",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        query_tokens = list(_catalog_tokens(query))
        conn = db()

        try:
            rows = _catalog_rows(conn, store_key)
            total = len(rows)
            hydrated_ok = sum(
                1 for row in rows
                if str(row["fetch_status"] or "").upper() == "OK"
            )
            pending_or_error = total - hydrated_ok

            candidates = []
            required = set(query_tokens)

            for row in rows:
                row_tokens = _catalog_row_tokens(row)
                if required and not required.issubset(row_tokens):
                    continue
                candidates.append(row)

            candidates = candidates[:max_candidates]
            queue = _catalog_queue_state(
                conn,
                store_key,
                [row["url"] for row in candidates],
            )

            if candidates:
                diagnosis = (
                    "CATALOG_CANDIDATES_FOUND: the active catalog contains "
                    "rows matching all query tokens. The next diagnostic "
                    "layer is search_local/catalog projection."
                )
            else:
                diagnosis = (
                    "NO_CATALOG_MATCH: no active catalog row contains all "
                    "query tokens across slug/name/brand."
                )

            return {
                "diagnostic": "catalog-store-read-only-v1",
                "ok": True,
                "production_search_called": False,
                "product_matcher_called": False,
                "scraper_called": False,
                "database_written": False,
                "store": store_key,
                "query": query,
                "query_tokens": query_tokens,
                "active_catalog_urls": total,
                "hydrated_ok": hydrated_ok,
                "pending_or_error": pending_or_error,
                "candidate_count": len(candidates),
                "candidates": [
                    _catalog_compact_row(row)
                    for row in candidates
                ],
                "hydration_queue_for_candidates": [
                    dict(item) for item in queue.values()
                ],
                "diagnosis": diagnosis,
                "elapsed_sec": round(time.monotonic() - started, 3),
            }
        finally:
            conn.close()

    except Exception as exc:
        return {
            "diagnostic": "catalog-store-read-only-v1",
            "ok": False,
            "production_search_called": False,
            "product_matcher_called": False,
            "scraper_called": False,
            "database_written": False,
            "store": store_key,
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-catalog-identity")
def diagnose_catalog_identity(
    store: str = Query("parfumzentrum"),
    q: str = Query("Rayhaan"),
    max_results: int = Query(100, ge=1, le=500),
):
    """Read-only trace with per-phase timings; never invokes live scrapers or writes."""
    started = time.monotonic()
    phase_sec = {
        "search_local": 0.0,
        "filter_and_copy_rows": 0.0,
        "clean_result_total": 0.0,
        "resolve_offer_identity_total": 0.0,
        "diagnostic_payload_build": 0.0,
    }
    clean_row_times = []
    identity_row_times = []
    store_key = str(store or "").strip().lower()
    query = str(q or "").strip()

    base = {
        "diagnostic": "catalog-identity-read-only-v2-timing",
        "ok": False,
        "production_search_called": False,
        "scraper_called": False,
        "discovery_called": False,
        "hydration_called": False,
        "database_written": False,
        "search_local_called": False,
        "clean_result_called": False,
        "resolve_offer_identity_called": False,
        "store": store_key,
        "query": query,
    }

    def timing_snapshot():
        return {
            "phase_sec": {key: round(value, 4) for key, value in phase_sec.items()},
            "phase_ms": {key: round(value * 1000, 2) for key, value in phase_sec.items()},
            "clean_result_rows_timed": len(clean_row_times),
            "resolve_rows_timed": len(identity_row_times),
            "clean_result_avg_ms": round(sum(clean_row_times) * 1000 / len(clean_row_times), 3) if clean_row_times else None,
            "clean_result_max_ms": round(max(clean_row_times) * 1000, 3) if clean_row_times else None,
            "resolve_avg_ms": round(sum(identity_row_times) * 1000 / len(identity_row_times), 3) if identity_row_times else None,
            "resolve_max_ms": round(max(identity_row_times) * 1000, 3) if identity_row_times else None,
        }

    try:
        from catalog_engine import STORES, search_local
        if store_key not in tuple(STORES):
            return {**base, "error": "invalid_store: available stores=" + ",".join(str(x) for x in STORES),
                    "elapsed_sec": round(time.monotonic() - started, 3), "timings": timing_snapshot()}
        if not query:
            return {**base, "error": "empty_query",
                    "elapsed_sec": round(time.monotonic() - started, 3), "timings": timing_snapshot()}

        phase_started = time.monotonic()
        raw_rows = search_local(query, per_store=max_results, search_terms=[query])
        phase_sec["search_local"] = time.monotonic() - phase_started
        base["search_local_called"] = True

        phase_started = time.monotonic()
        rows = []
        for row in list(raw_rows or []):
            item = dict(row) if not isinstance(row, dict) else dict(row)
            if str(item.get("store") or "").strip().lower() == store_key:
                rows.append(item)
        rows = rows[:max_results]
        phase_sec["filter_and_copy_rows"] = time.monotonic() - phase_started

        import main as main_module
        clean_fn = getattr(main_module, "clean_result", None)
        resolve_fn = getattr(main_module, "_resolve_offer_identity", None)
        if not callable(clean_fn):
            return {**base, "error": "main.clean_result_unavailable", "row_count": len(rows),
                    "elapsed_sec": round(time.monotonic() - started, 3), "timings": timing_snapshot()}
        if not callable(resolve_fn):
            return {**base, "error": "main._resolve_offer_identity_unavailable", "row_count": len(rows),
                    "elapsed_sec": round(time.monotonic() - started, 3), "timings": timing_snapshot()}

        inspected = []
        for index, raw in enumerate(rows):
            item = {
                "index": index,
                "raw": {
                    "name": raw.get("name"),
                    "brand": raw.get("brand"),
                    "url": raw.get("url"),
                    "price": raw.get("price"),
                    "availability": raw.get("availability"),
                    "size_ml": raw.get("size_ml"),
                    "fetch_status": raw.get("fetch_status"),
                    "source": raw.get("source"),
                },
            }
            try:
                phase_started = time.monotonic()
                cleaned = clean_fn(dict(raw), store_key)
                clean_elapsed = time.monotonic() - phase_started
                phase_sec["clean_result_total"] += clean_elapsed
                clean_row_times.append(clean_elapsed)
                base["clean_result_called"] = True
                if not isinstance(cleaned, dict):
                    item["clean"] = {"type": type(cleaned).__name__, "value": str(cleaned)[:1000]}
                    item["identity"] = {"status": "CLEAN_RESULT_NON_DICT"}
                    inspected.append(item)
                    continue
                item["clean"] = {
                    "name": cleaned.get("name"),
                    "brand": cleaned.get("brand"),
                    "_raw_name": cleaned.get("_raw_name"),
                    "_raw_brand": cleaned.get("_raw_brand"),
                    "url": cleaned.get("url"),
                    "price": cleaned.get("price"),
                    "availability": cleaned.get("availability"),
                    "size_ml": cleaned.get("size_ml"),
                    "store": cleaned.get("store"),
                }
                try:
                    phase_started = time.monotonic()
                    resolved = resolve_fn(dict(cleaned), query)
                    identity_elapsed = time.monotonic() - phase_started
                    phase_sec["resolve_offer_identity_total"] += identity_elapsed
                    identity_row_times.append(identity_elapsed)
                    base["resolve_offer_identity_called"] = True
                    if isinstance(resolved, dict):
                        item["identity"] = {
                            "returned": True,
                            "match_status": resolved.get("_match_status"),
                            "catalog_id": resolved.get("catalog_id"),
                            "canonical_name": resolved.get("canonical_name"),
                            "canonical_brand": resolved.get("canonical_brand"),
                            "canonical_size_ml": resolved.get("canonical_size_ml"),
                            "match_method": resolved.get("match_method"),
                            "match_score": resolved.get("match_score"),
                            "match_error": resolved.get("_match_error"),
                            "needs_refresh": resolved.get("_needs_refresh"),
                        }
                    else:
                        item["identity"] = {
                            "returned": False,
                            "return_type": type(resolved).__name__,
                            "return_value": str(resolved)[:1000],
                        }
                except Exception as exc:
                    item["identity"] = {
                        "returned": False,
                        "exception": f"{type(exc).__name__}: {exc}",
                    }
            except Exception as exc:
                item["clean_error"] = f"{type(exc).__name__}: {exc}"
            inspected.append(item)

        phase_started = time.monotonic()
        total_elapsed = time.monotonic() - started
        phase_sec["diagnostic_payload_build"] = max(0.0, time.monotonic() - phase_started)
        timings = timing_snapshot()
        timings["total_elapsed_sec"] = round(total_elapsed, 4)
        timings["unaccounted_sec"] = round(max(0.0, total_elapsed - sum(phase_sec.values())), 4)
        timings["rows_returned"] = len(inspected)
        timings["matched_rows"] = sum(1 for row in inspected if (row.get("identity") or {}).get("match_status") == "matched")
        timings["rejected_rows"] = sum(1 for row in inspected if (row.get("identity") or {}).get("match_status") == "rejected")
        timings["error_rows"] = sum(1 for row in inspected if "clean_error" in row or ((row.get("identity") or {}).get("returned") is False and (row.get("identity") or {}).get("exception")))
        return {
            **base,
            "ok": True,
            "row_count": len(rows),
            "rows": inspected,
            "timings": timings,
            "diagnosis": (
                "READ_ONLY_TIMING_TRACE: timings separate catalog search, row filtering, "
                "clean_result, and _resolve_offer_identity. No production search, scraper, "
                "discovery, hydration, or database write was invoked."
            ),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            **base,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
            "timings": timing_snapshot(),
        }


@router.get("/diagnose-catalog-search-local")
def diagnose_catalog_search_local(
    store: str = Query("parfumzentrum"),
    q: str = Query("Rayhaan"),
    max_results: int = Query(100, ge=1, le=500),
):
    """Read-only trace of the persistent catalog through search_local().

    This endpoint deliberately calls ONLY catalog_engine.search_local(). It
    does not call retailer scrapers, ProductMatcher, discovery, hydration,
    the public /search route, or any database write operation.
    """
    started = time.monotonic()
    store_key = str(store or "").strip().lower()
    query = str(q or "").strip()

    try:
        from catalog_engine import STORES, search_local

        if store_key not in tuple(STORES):
            return {
                "diagnostic": "catalog-search-local-read-only-v1",
                "ok": False,
                "production_search_called": False,
                "product_matcher_called": False,
                "scraper_called": False,
                "database_written": False,
                "search_local_called": False,
                "store": store_key,
                "query": query,
                "error": "invalid_store: available stores=" + ",".join(str(item) for item in STORES),
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        if not query:
            return {
                "diagnostic": "catalog-search-local-read-only-v1",
                "ok": False,
                "production_search_called": False,
                "product_matcher_called": False,
                "scraper_called": False,
                "database_written": False,
                "search_local_called": False,
                "store": store_key,
                "query": query,
                "error": "empty_query",
                "elapsed_sec": round(time.monotonic() - started, 3),
            }

        search_terms = [query]
        raw_rows = search_local(
            query,
            per_store=max_results,
            search_terms=search_terms,
        )

        rows = list(raw_rows or [])
        store_rows = []
        for row in rows:
            if isinstance(row, dict):
                row_store = str(row.get("store") or "").strip().lower()
                if row_store == store_key:
                    store_rows.append(dict(row))
            else:
                try:
                    item = dict(row)
                except Exception:
                    item = {"value": str(row)}
                row_store = str(item.get("store") or "").strip().lower()
                if row_store == store_key:
                    store_rows.append(item)

        store_rows = store_rows[:max_results]

        return {
            "diagnostic": "catalog-search-local-read-only-v1",
            "ok": True,
            "production_search_called": False,
            "product_matcher_called": False,
            "scraper_called": False,
            "database_written": False,
            "search_local_called": True,
            "store": store_key,
            "query": query,
            "search_terms": search_terms,
            "catalog_search_row_count_all_stores": len(rows),
            "catalog_search_row_count_store": len(store_rows),
            "rows": store_rows,
            "diagnosis": (
                "SEARCH_LOCAL_RETURNS_STORE_ROWS: catalog projection exposes rows "
                "for this store; next layer is main.py catalog report/identity resolution."
                if store_rows else
                "SEARCH_LOCAL_RETURNS_NO_STORE_ROWS: the catalog contains matching "
                "SQLite rows but search_local() did not project any row for this store."
            ),
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    except Exception as exc:
        return {
            "diagnostic": "catalog-search-local-read-only-v1",
            "ok": False,
            "production_search_called": False,
            "product_matcher_called": False,
            "scraper_called": False,
            "database_written": False,
            "search_local_called": True,
            "store": store_key,
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }


@router.get("/diagnose-catalog-path")
def diagnose_catalog_path(
    q: str = Query("Liquid Brun"),
    terms: str = Query(""),
    max_candidates: int = Query(50, ge=1, le=200),
):
    """Fast, strictly read-only catalog diagnostic.

    IMPORTANT: this endpoint deliberately does NOT import main, call
    search_local(), run ProductMatcher, discover URLs, hydrate pages, or touch
    the production search cache. It only reads SQLite and reports whether the
    requested tokens are already present in the active catalog.
    """
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"

    if terms.strip():
        search_terms = [x.strip() for x in terms.split(",") if x.strip()]
    else:
        search_terms = [query]

    term_tokens = {term: list(_catalog_tokens(term)) for term in search_terms}

    try:
        from catalog_engine import db
        conn = db()
    except Exception as exc:
        return {
            "diagnostic": "catalog-path-read-only-v2",
            "ok": False,
            "query": query,
            "search_terms": search_terms,
            "term_tokens": term_tokens,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    result = {
        "diagnostic": "catalog-path-read-only-v2",
        "ok": True,
        "query": query,
        "search_terms": search_terms,
        "term_tokens": term_tokens,
        "production_search_called": False,
        "product_matcher_called": False,
        "database_written": False,
        "stores": {},
    }

    try:
        for store in TARGET_STORES:
            rows = _catalog_rows(conn, store)
            total = len(rows)
            hydrated = [
                r for r in rows
                if str(r["fetch_status"] or "").upper() == "OK"
            ]

            per_term = {}
            union = {}

            for term in search_terms:
                wanted = set(_catalog_tokens(term))
                if not wanted:
                    per_term[term] = {
                        "required_tokens": [],
                        "candidate_count": 0,
                        "candidates": [],
                    }
                    continue

                hits = []
                for row in rows:
                    row_tokens = _catalog_row_tokens(row)
                    if wanted.issubset(row_tokens):
                        hits.append(row)
                        union[row["url"]] = row

                per_term[term] = {
                    "required_tokens": sorted(wanted),
                    "candidate_count": len(hits),
                    "candidates": [
                        _catalog_compact_row(dict(r))
                        for r in hits[:max_candidates]
                    ],
                }

            union_rows = list(union.values())

            token_locations = []
            for row in union_rows[:max_candidates]:
                item = dict(row)
                field_tokens = {
                    "slug": _catalog_token_set(item.get("slug")),
                    "name": _catalog_token_set(item.get("product_name")),
                    "brand": _catalog_token_set(item.get("product_brand")),
                }
                locations = {}
                for term, required in term_tokens.items():
                    required_set = set(required)
                    if required_set:
                        locations[term] = {
                            field: sorted(required_set.intersection(values))
                            for field, values in field_tokens.items()
                            if required_set.intersection(values)
                        }
                token_locations.append({
                    **_catalog_compact_row(item),
                    "token_locations": locations,
                })

            queue = _catalog_queue_state(
                conn,
                store,
                [r["url"] for r in union_rows[:max_candidates]],
            )

            if not union_rows:
                diagnosis = (
                    "NO_CATALOG_MATCH: nessun URL attivo di questo store "
                    "contiene tutti i token richiesti nei campi slug/nome/marca. "
                    "Il problema è a monte di search_local."
                )
            else:
                diagnosis = (
                    "CATALOG_MATCH_FOUND: il catalogo contiene candidati. "
                    "Il prossimo test deve verificare perché search_local "
                    "non li espone nella ricerca pubblica."
                )

            result["stores"][store] = {
                "active_catalog_urls": total,
                "hydrated_ok": len(hydrated),
                "pending_or_error": total - len(hydrated),
                "per_term": per_term,
                "union_candidate_count": len(union_rows),
                "union_candidates": [
                    _catalog_compact_row(dict(r))
                    for r in union_rows[:max_candidates]
                ],
                "token_locations": token_locations,
                "hydration_queue_for_candidates": list(queue.values())[:max_candidates],
                "diagnosis": diagnosis,
            }
    finally:
        conn.close()

    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result

@router.get("/diagnose-parfumzentrum-refresh-path")
def diagnose_parfumzentrum_refresh_path(
    url: str = Query(...),
):
    """Read-only replay of catalog_engine.refresh_url() for one ParfumZentrum URL.

    The real DB writer is replaced with a capture-only connection, so the exact
    production refresh path can be executed without persisting anything.
    """
    started = time.monotonic()
    target = str(url or "").strip()
    base = {
        "diagnostic": "parfumzentrum-refresh-path-v1",
        "ok": False,
        "read_only": True,
        "store": "parfumzentrum",
        "url": target,
        "database_written": False,
        "purpose": (
            "execute the deployed catalog_engine.refresh_url() path for one "
            "exact ParfumZentrum URL while replacing the real DB connection "
            "with a capture-only connection"
        ),
    }

    if not target.startswith("https://www.parfum-zentrum.de/"):
        return {**base, "error": "url_not_allowed", "elapsed_sec": round(time.monotonic() - started, 3)}

    class _CaptureConnection:
        def __init__(self):
            self.executions = []

        def execute(self, sql, params=()):
            self.executions.append({
                "sql": " ".join(str(sql).split()),
                "params": list(params) if params is not None else [],
            })
            return self

        def commit(self):
            return None

        def close(self):
            return None

    try:
        import catalog_engine as ce

        capture = _CaptureConnection()
        real_db = ce.db
        real_index = getattr(ce, "_update_local_search_index_product", None)
        ce.db = lambda: capture
        if callable(real_index):
            ce._update_local_search_index_product = lambda *args, **kwargs: None

        try:
            item = ce.refresh_url("parfumzentrum", target)
        finally:
            ce.db = real_db
            if callable(real_index):
                ce._update_local_search_index_product = real_index

        persisted_params = None
        for execution in capture.executions:
            params = execution.get("params") or []
            if len(params) >= 16 and params[0] == "parfumzentrum" and params[1] == target:
                persisted_params = params
                break

        persisted = None
        if persisted_params is not None:
            persisted = {
                "store": persisted_params[0],
                "url": persisted_params[1],
                "name": persisted_params[2],
                "brand": persisted_params[3],
                "sku": persisted_params[5],
                "gtin": persisted_params[6],
                "price": persisted_params[11],
                "currency": persisted_params[12],
                "availability": persisted_params[13],
                "fetched_at": persisted_params[14],
                "fetch_status": persisted_params[15],
            }

        return {
            **base,
            "ok": True,
            "refresh_returned": bool(item),
            "refresh_item": item,
            "captured_db_executions": len(capture.executions),
            "persisted_record_would_be": persisted,
            "database_write_intercepted": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "diagnosis": (
                "REFRESH_PATH_CAPTURED: compare refresh_item.price_num with "
                "persisted_record_would_be.price. If they differ, the discrepancy "
                "is inside the deployed refresh/persistence path."
            ),
        }
    except Exception as exc:
        return {
            **base,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

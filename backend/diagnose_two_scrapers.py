from fastapi import APIRouter, Query
import concurrent.futures
import re
import time
from urllib.parse import quote, urljoin

import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}
TOKEN_RE = re.compile(r"\b(liquid|brun)\b", re.I)


def _get(url, timeout=(1.5, 5.0), headers=None):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "ok": True,
            "status": r.status_code,
            "url": r.url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": len(r.content),
            "text": r.text,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": 0,
            "text": "",
            "error": f"{type(e).__name__}: {e}",
        }


def _compact(s, n=500):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n]


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
        for marker in [q, "liquid brun", "liquid-brun", "34982", "720100",
                       "french avenue", "profumi-da-uomo", "/it/profumi-da-uomo/"]:
            i = low.find(marker.lower())
            hits[marker] = None if i < 0 else {
                "offset": i,
                "context": _compact(text[max(0, i-350):i+700], 1050)
            }

        links = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
            href = m.group(1)
            if any(x in href.lower() for x in ["34982", "liquid", "brun", "profumi-da-uomo"]):
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
        "elapsed_sec": round(time.monotonic()-started, 3),
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
        pages = list(ex.map(lambda u: _get(u, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}), urls))

    out = []
    for p in pages:
        text = p["text"]
        matches = []
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
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
            raw_contexts.append(_compact(text[max(0, m.start()-300):m.end()+500], 900))
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
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of category/card text; no URL-token discovery and no production search()",
        "pages": out,
    }


@router.get("/diagnose-sabina-discovery-trace")
def diagnose_sabina_discovery_trace(q: str = Query("9 PM")):
    """Deep read-only trace of Sabina discovery stages."""
    started = time.monotonic()
    out = {"diagnostic": True, "store": "Sabina", "query": q,
           "purpose": "read-only trace of deployed Sabina discovery stages"}
    try:
        from scrapers.sabina import scraper
        session = requests.Session()
        try:
            out["scraper_module"] = getattr(scraper, "__file__", None)
            trace = {}
            search_url = f"{scraper.SEARCH_URL}?search_query={quote(q)}"
            page = _get(search_url, timeout=(2, 8), headers=getattr(scraper, "HEADERS", HEADERS))
            trace["search_page"] = {k: page[k] for k in ("ok","status","url","elapsed_sec","bytes","error")}
            text = page["text"]
            links = []
            if text:
                for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
                    u = urljoin(page["url"], m.group(1))
                    if scraper.is_product_url(u):
                        links.append(u)
            trace["search_product_urls"] = list(dict.fromkeys(links))[:100]

            robots_url = scraper.BASE_URL + "/robots.txt"
            robots = _get(robots_url, timeout=(2, 8), headers=getattr(scraper, "HEADERS", HEADERS))
            trace["robots"] = {k: robots[k] for k in ("ok","status","url","elapsed_sec","bytes","error")}
            sitemap_refs = re.findall(r'(?im)^\s*Sitemap:\s*(https?://\S+)', robots["text"] or "")
            trace["robots_sitemaps"] = sitemap_refs[:100]

            sitemap_http_trace = []
            for sitemap_url in sitemap_refs[:20]:
                sp = _get(sitemap_url, timeout=(2, 12), headers=getattr(scraper, "HEADERS", HEADERS))
                body = sp["text"] or ""
                locs = re.findall(r"<\s*loc(?:\s[^>]*)?>\s*(.*?)\s*</\s*loc\s*>", body, re.I | re.S)
                sitemap_http_trace.append({
                    "url": sitemap_url,
                    "ok": sp["ok"],
                    "status": sp["status"],
                    "elapsed_sec": sp["elapsed_sec"],
                    "bytes": sp["bytes"],
                    "error": sp["error"],
                    "loc_count": len(locs),
                    "loc_sample": [re.sub(r"\s+", " ", x).strip() for x in locs[:20]],
                    "head": re.sub(r"\s+", " ", body[:1500]).strip(),
                })
            trace["sitemap_http_trace"] = sitemap_http_trace

            sitemap_fn = getattr(scraper, "_discover_from_sitemaps", None)
            if sitemap_fn:
                try:
                    result = sitemap_fn(session, q)
                    trace["sitemap_discovery"] = {"ok": True, "count": len(result or []), "urls": (result or [])[:100]}
                except Exception as exc:
                    trace["sitemap_discovery"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            else:
                trace["sitemap_discovery"] = {"ok": False, "error": "_discover_from_sitemaps not found"}

            score_fn = getattr(scraper, "_catalog_candidate_score", None)
            candidates = []
            if score_fn and trace.get("sitemap_discovery", {}).get("ok"):
                for u in trace["sitemap_discovery"]["urls"]:
                    try:
                        candidates.append({"url": u, "score": score_fn(u, q)})
                    except Exception as exc:
                        candidates.append({"url": u, "score_error": f"{type(exc).__name__}: {exc}"})
            trace["sitemap_scored_candidates"] = sorted(candidates, key=lambda x: x.get("score", -1), reverse=True)[:100]

            final = scraper.discover_product_urls(session, q)
            trace["final_discovery"] = {"count": len(final or []), "urls": (final or [])[:100]}
            out["trace"] = trace
        finally:
            session.close()
        out["elapsed_sec"] = round(time.monotonic() - started, 3)
        return out
    except Exception as exc:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


# ============================================================================
# CATALOG-FIRST DIAGNOSTIC
# ============================================================================
# This endpoint is deliberately read-only. It does not discover URLs, hydrate
# pages, write the database, invalidate the production cache, or alter search.
# It traces the exact point at which Sabina/Deloox disappear from the catalog
# path: active catalog -> token match -> search_local -> ProductMatcher.

TARGET_STORES = ("sabina", "deloox")


def _catalog_token_set(value):
    try:
        from catalog_engine import norm
        return set(norm(str(value or "")).split())
    except Exception:
        return set(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


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
        "url": row.get("url"),
        "slug": row.get("slug"),
        "name": row.get("product_name"),
        "brand": row.get("product_brand"),
        "fetch_status": row.get("fetch_status"),
        "fetched_at": row.get("fetched_at"),
        "lastmod": row.get("lastmod"),
        "discovered_at": row.get("discovered_at"),
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


def _catalog_matcher_snapshot(rows, query, store):
    """Run the same final identity path used by main.py, read-only."""
    out = {
        "available": False,
        "error": None,
        "matched": 0,
        "unresolved": 0,
        "rejected": 0,
        "samples": [],
    }
    try:
        import main
        out["available"] = True
        for raw in rows[:64]:
            item = dict(raw)
            # Convert the diagnostic DB column names back to the public offer
            # shape expected by clean_result()/ProductMatcher.
            item["name"] = item.get("product_name") or item.get("name") or ""
            item["brand"] = item.get("product_brand") or item.get("brand") or ""
            item["store_key"] = store
            item["store"] = main.STORE_LABELS.get(store, store)
            item["shop"] = item["store"]
            prepared = main.clean_result(item, store)
            if prepared is None or main._is_non_fragrance_offer(prepared):
                continue
            resolved = main._resolve_offer_identity(prepared, query)
            if not isinstance(resolved, dict):
                continue
            status = resolved.get("_match_status") or "unresolved"
            if status == "matched":
                out["matched"] += 1
            elif status == "rejected":
                out["rejected"] += 1
            else:
                out["unresolved"] += 1
            if len(out["samples"]) < 12:
                out["samples"].append({
                    "url": item.get("url"),
                    "name": item.get("name"),
                    "brand": item.get("brand"),
                    "match_status": resolved.get("_match_status"),
                    "catalog_id": resolved.get("catalog_id"),
                    "canonical_name": resolved.get("canonical_name"),
                    "canonical_brand": resolved.get("canonical_brand"),
                    "match_method": resolved.get("match_method"),
                    "match_score": resolved.get("match_score"),
                    "reject_reason": resolved.get("_reject_reason"),
                    "match_error": resolved.get("_match_error"),
                })
        return out
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


@router.get("/diagnose-catalog-path")
def diagnose_catalog_path(
    q: str = Query("Liquid Brun"),
    terms: str = Query(""),
):
    """Deep read-only trace of the catalog-first path for Sabina and Deloox."""
    started = time.monotonic()
    query = str(q or "").strip() or "Liquid Brun"

    try:
        import main
        if terms.strip():
            search_terms = [x.strip() for x in terms.split(",") if x.strip()]
        else:
            search_terms = list(main._catalog_search_terms(query) or [query])
    except Exception as exc:
        search_terms = [query]
        main_import_error = f"{type(exc).__name__}: {exc}"
    else:
        main_import_error = None

    term_tokens = {term: list(_catalog_tokens(term)) for term in search_terms}

    try:
        from catalog_engine import db, search_local
        conn = db()
    except Exception as exc:
        return {
            "diagnostic": "catalog-path-read-only-v1",
            "ok": False,
            "query": query,
            "search_terms": search_terms,
            "term_tokens": term_tokens,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_sec": round(time.monotonic() - started, 3),
        }

    result = {
        "diagnostic": "catalog-path-read-only-v1",
        "ok": True,
        "query": query,
        "search_terms": search_terms,
        "term_tokens": term_tokens,
        "main_import_error": main_import_error,
        "stores": {},
    }

    try:
        try:
            local_rows = search_local(
                query,
                per_store=128,
                search_terms=search_terms,
            ) or []
        except TypeError:
            local_rows = search_local(query, per_store=128) or []

        local_by_store = {store: [] for store in TARGET_STORES}
        for row in local_rows:
            store = str(row.get("store_key") or "").strip().lower()
            if store in local_by_store:
                local_by_store[store].append(row)

        for store in TARGET_STORES:
            rows = _catalog_rows(conn, store)
            total = len(rows)
            hydrated = [r for r in rows if str(r["fetch_status"] or "") == "OK"]

            per_term = {}
            exact_candidates = {}
            for term in search_terms:
                wanted = set(_catalog_tokens(term))
                if not wanted:
                    continue
                hits = [r for r in rows if wanted.issubset(_catalog_row_tokens(r))]
                per_term[term] = {
                    "required_tokens": sorted(wanted),
                    "candidate_count": len(hits),
                    "candidates": [_catalog_compact_row(dict(r)) for r in hits[:30]],
                }
                exact_candidates[term] = hits

            union = {}
            for hits in exact_candidates.values():
                for row in hits:
                    union[row["url"]] = row
            union_rows = list(union.values())
            queue = _catalog_queue_state(conn, store, [r["url"] for r in union_rows])

            actual_local = local_by_store[store]
            actual_urls = [str(r.get("url") or "") for r in actual_local]
            matcher = _catalog_matcher_snapshot(union_rows, query, store)

            if not union_rows:
                diagnosis = "NO_CATALOG_MATCH: il blocco è prima di search_local; nessun URL attivo contiene tutti i token richiesti nei campi slug/nome/marca."
            elif not actual_local:
                diagnosis = "CATALOG_MATCH_BUT_SEARCH_LOCAL_EMPTY: il DB contiene candidati ma search_local non li restituisce. Questo è il punto da indagare nell'indice/cache/search_local."
            elif matcher.get("matched", 0) == 0 and matcher.get("unresolved", 0) + matcher.get("rejected", 0) > 0:
                diagnosis = "SEARCH_LOCAL_MATCHES_BUT_MATCHER_DOES_NOT_RESOLVE: i candidati arrivano dal catalogo; il problema è successivo, nel clean_result/ProductMatcher."
            else:
                diagnosis = "CATALOG_PATH_REACHES_MATCHER: Sabina/Deloox superano catalogo e matcher per almeno un candidato; confrontare questi URL con il risultato pubblico della ricerca."

            result["stores"][store] = {
                "active_catalog_urls": total,
                "hydrated_ok": len(hydrated),
                "pending_or_error": total - len(hydrated),
                "per_term": per_term,
                "union_candidate_count": len(union_rows),
                "union_candidates": [_catalog_compact_row(dict(r)) for r in union_rows[:50]],
                "hydration_queue_for_candidates": list(queue.values())[:50],
                "search_local_candidate_count": len(actual_local),
                "search_local_candidates": [
                    {
                        "url": r.get("url"),
                        "name": r.get("name"),
                        "brand": r.get("brand"),
                        "fetch_status": r.get("fetch_status"),
                        "needs_refresh": bool(r.get("_needs_refresh")),
                    }
                    for r in actual_local[:50]
                ],
                "search_local_urls": actual_urls[:50],
                "matcher_on_catalog_candidates": matcher,
                "diagnosis": diagnosis,
            }
    finally:
        conn.close()

    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result

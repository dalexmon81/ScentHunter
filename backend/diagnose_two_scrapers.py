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

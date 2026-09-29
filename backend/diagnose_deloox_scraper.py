from fastapi import APIRouter, Query
import concurrent.futures
import re
import time
from urllib.parse import quote, urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17_0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}
TOKEN_RE = re.compile(r"\b(liquid|brun)\b", re.I)


def _get(url, timeout=(1.5, 5.0), headers=None):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {"ok": True, "status": r.status_code, "url": r.url,
                "elapsed_sec": round(time.monotonic() - t, 3), "bytes": len(r.content),
                "text": r.text, "error": None}
    except Exception as e:
        return {"ok": False, "status": None, "url": url,
                "elapsed_sec": round(time.monotonic() - t, 3), "bytes": 0,
                "text": "", "error": f"{type(e).__name__}: {e}"}


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
    urls = [f"{base}/it/ricerca_old?s={quote(q)}",
            f"{base}/it/ricerca?search_query={quote(q)}",
            f"{base}/it/ricerca_old?search_query={quote(q)}"]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u), urls))
    probes = []
    for p in pages:
        text = p["text"]; low = text.lower(); hits = {}
        for marker in [q, "liquid brun", "liquid-brun", "34982", "720100",
                       "french avenue", "profumi-da-uomo", "/it/profumi-da-uomo/"]:
            i = low.find(marker.lower())
            hits[marker] = None if i < 0 else {"offset": i,
                "context": _compact(text[max(0, i-350):i+700], 1050)}
        links = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
            href = m.group(1)
            if any(x in href.lower() for x in ["34982", "liquid", "brun", "profumi-da-uomo"]):
                links.append(urljoin(p["url"], href))
        probes.append({"url": p["url"], "status": p["status"], "elapsed_sec": p["elapsed_sec"],
                       "bytes": p["bytes"], "error": p["error"],
                       "matching_links": list(dict.fromkeys(links))[:50], "markers": hits})
    return {"diagnostic": True, "store": "Sabina", "query": q,
            "elapsed_sec": round(time.monotonic()-started, 3),
            "purpose": "read-only inspection of real search responses",
            "probes": probes}


@router.get("/diagnose-sabina-discovery-trace")
def diagnose_sabina_discovery_trace(q: str = Query("9 PM")):
    started = time.monotonic()
    out = {"diagnostic": True, "store": "Sabina", "query": q,
           "purpose": "read-only trace of deployed Sabina discovery stages"}
    try:
        from scrapers.sabina import scraper
        session = requests.Session()
        try:
            out["scraper_module"] = getattr(scraper, "__file__", None)
            search_url = f"{scraper.SEARCH_URL}?search_query={quote(q)}"
            page = _get(search_url, timeout=(2,8), headers=getattr(scraper, "HEADERS", HEADERS))
            text = page["text"]; links = []
            for m in re.finditer(r'href=["\']([^"\']+)["\']', text or "", re.I):
                u = urljoin(page["url"], m.group(1))
                if scraper.is_product_url(u): links.append(u)
            out["search_page"] = {k: page[k] for k in ("ok","status","url","elapsed_sec","bytes","error")}
            out["search_product_urls"] = list(dict.fromkeys(links))[:100]
            robots = _get(scraper.BASE_URL + "/robots.txt", timeout=(2,8), headers=getattr(scraper,"HEADERS",HEADERS))
            out["robots"] = {k: robots[k] for k in ("ok","status","url","elapsed_sec","bytes","error")}
            refs = re.findall(r"(?im)^\s*Sitemap:\s*(https?://\S+)", robots["text"] or "")
            out["robots_sitemaps"] = refs[:100]
            sitemap_trace = []
            for u in refs[:20]:
                sp = _get(u, timeout=(2,12), headers=getattr(scraper,"HEADERS",HEADERS))
                body = sp["text"] or ""
                locs = re.findall(r"<\s*loc(?:\s[^>]*)?>\s*(.*?)\s*</\s*loc\s*>", body, re.I|re.S)
                sitemap_trace.append({"url":u,"ok":sp["ok"],"status":sp["status"],
                    "elapsed_sec":sp["elapsed_sec"],"bytes":sp["bytes"],"error":sp["error"],
                    "loc_count":len(locs),"loc_sample":[re.sub(r"\s+"," ",x).strip() for x in locs[:20]]})
            out["sitemap_http_trace"] = sitemap_trace
            fn = getattr(scraper, "_discover_from_sitemaps", None)
            out["sitemap_discovery"] = ({"ok":True,"count":len(fn(session,q) or [])}
                                        if fn else {"ok":False,"error":"_discover_from_sitemaps not found"})
            final = scraper.discover_product_urls(session,q)
            out["final_discovery"] = {"count":len(final or []),"urls":(final or [])[:100]}
        finally:
            session.close()
        out["elapsed_sec"] = round(time.monotonic()-started,3)
        return out
    except Exception as exc:
        out["elapsed_sec"] = round(time.monotonic()-started,3)
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


@router.get("/diagnose-discovery-trace")
def diagnose_discovery_trace(q: str = Query("Liquid Brun"), max_sitemaps: int = Query(1000,ge=1,le=5000),
                             max_samples: int = Query(30,ge=1,le=200)):
    started=time.monotonic(); query=str(q or "").strip() or "Liquid Brun"
    result={"diagnostic":"generic-discovery-trace-v3","ok":True,"query":query,
            "purpose":"read-only replay of catalog_engine sitemap discovery; no writes, search, hydration or matcher",
            "stores":{}}
    try:
        import catalog_engine as ce
        wanted=set(ce.tokens(query))
        threshold=int(getattr(ce,"HTML_FALLBACK_SITEMAP_PRODUCT_THRESHOLD",0) or 0)
        for store in ("sabina","deloox"):
            st=time.monotonic()
            try: roots, robots_diag=ce._seed_sitemaps(store)
            except Exception as exc:
                result["stores"][store]={"ok":False,"stage":"seed_sitemaps",
                    "error":f"{type(exc).__name__}: {exc}"}; continue
            queue=[(u,0) for u in roots]; queued=set(roots); visited=set(); products=set()
            errors=[]; successes=0; xml_entries=0; index_entries=0; product_entries=0; hits=[]
            while queue and len(visited)<min(max_sitemaps,ce.MAX_SITEMAPS_PER_STORE) and len(products)<ce.MAX_TOTAL_DISCOVERED_URLS and time.monotonic()-st<ce.DISCOVERY_HARD_TIMEOUT:
                batch=[]
                while queue and len(batch)<ce.SYNC_WORKERS*4:
                    sm,d=queue.pop(0)
                    if sm in visited: continue
                    visited.add(sm); batch.append((sm,d))
                if not batch: continue
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(ce.SYNC_WORKERS,len(batch))) as pool:
                    fs={pool.submit(ce._fetch_sitemap,store,sm):(sm,d) for sm,d in batch}
                    for f in concurrent.futures.as_completed(fs):
                        sm,d=fs[f]
                        try: source,final,entries,error=f.result()
                        except Exception as exc: final,entries,error=sm,[],f"EXCEPTION:{type(exc).__name__}:{exc}"
                        if error: errors.append({"sitemap":sm,"depth":d,"error":error}); continue
                        successes+=1; xml_entries+=len(entries)
                        for kind,raw,lastmod in entries:
                            absolute=urljoin(final or sm,raw.strip()) if raw else ""
                            if not absolute: continue
                            if kind=="sitemap":
                                index_entries+=1
                                if d+1<=ce.MAX_SITEMAP_DEPTH and absolute not in queued:
                                    queued.add(absolute); queue.append((absolute,d+1))
                                continue
                            if not ce._looks_product(absolute): continue
                            products.add(absolute); product_entries+=1
                            if wanted and wanted.issubset(set(ce.tokens(absolute))) and len(hits)<max_samples: hits.append(absolute)
            seeds=getattr(ce,"HTML_DISCOVERY_SEEDS",{}).get(store,()) or ()
            result["stores"][store]={"ok":True,"roots_found":len(roots),
                "sitemaps_visited":len(visited),"sitemaps_successful":successes,"sitemap_errors":len(errors),
                "sitemap_error_samples":errors[:max_samples],"xml_entries_seen":xml_entries,
                "sitemap_index_entries":index_entries,"product_urls_seen":len(products),
                "product_entries_seen":product_entries,"query_url_hits":len(hits),
                "query_url_hit_samples":hits[:max_samples],
                "html_fallback":{"threshold":threshold,"seed_count":len(seeds),"seeds":list(seeds)[:20],
                    "would_execute_in_production_discovery": (len(products)<threshold if threshold else len(products)==0)},
                "elapsed_sec":round(time.monotonic()-st,3)}
    except Exception as exc:
        result["ok"]=False; result["error"]=f"{type(exc).__name__}: {exc}"
    result["elapsed_sec"]=round(time.monotonic()-started,3)
    return result


TARGET_STORES=("sabina","deloox")

def _catalog_token_set(value):
    try:
        from catalog_engine import norm
        return set(norm(str(value or "")).split())
    except Exception:
        return set(re.sub(r"[^a-z0-9]+"," ",str(value or "").lower()).split())

def _catalog_tokens(value):
    try:
        from catalog_engine import tokens
        return tuple(tokens(str(value or "")))
    except Exception:
        return tuple(_catalog_token_set(value))

def _catalog_row_tokens(row):
    return _catalog_token_set(" ".join(str(row[key] or "") for key in ("slug","product_name","product_brand")))

def _catalog_compact_row(row):
    return {"url":row.get("url"),"slug":row.get("slug"),"name":row.get("product_name"),
            "brand":row.get("product_brand"),"fetch_status":row.get("fetch_status"),
            "fetched_at":row.get("fetched_at"),"lastmod":row.get("lastmod"),
            "discovered_at":row.get("discovered_at")}

def _catalog_rows(conn,store):
    return conn.execute("""SELECT u.url,u.slug,u.lastmod,u.discovered_at,
                                  p.name AS product_name,p.brand AS product_brand,
                                  p.fetch_status,p.fetched_at
                           FROM store_urls u
                           LEFT JOIN store_products p ON p.store=u.store AND p.url=u.url
                           WHERE u.store=? AND u.active=1 ORDER BY u.url""",(store,)).fetchall()

def _catalog_queue_state(conn,store,urls):
    if not urls: return {}
    ph=",".join("?" for _ in urls)
    rows=conn.execute(f"""SELECT store,url,state,attempts,last_error,last_http_status,
                                  last_started_at,last_finished_at,available_at
                           FROM hydration_queue WHERE store=? AND url IN ({ph})""",
                      (store,*urls)).fetchall()
    return {r["url"]:dict(r) for r in rows}

@router.get("/diagnose-catalog-path")
def diagnose_catalog_path(q: str=Query("Liquid Brun"), terms: str=Query(""),
                          max_candidates:int=Query(50,ge=1,le=200)):
    started=time.monotonic(); query=str(q or "").strip() or "Liquid Brun"
    search_terms=[x.strip() for x in terms.split(",") if x.strip()] if terms.strip() else [query]
    term_tokens={t:list(_catalog_tokens(t)) for t in search_terms}
    try:
        from catalog_engine import db
        conn=db()
    except Exception as exc:
        return {"diagnostic":"catalog-path-read-only-v2","ok":False,"query":query,
                "error":f"{type(exc).__name__}: {exc}","elapsed_sec":round(time.monotonic()-started,3)}
    result={"diagnostic":"catalog-path-read-only-v2","ok":True,"query":query,
            "search_terms":search_terms,"term_tokens":term_tokens,
            "production_search_called":False,"product_matcher_called":False,
            "database_written":False,"stores":{}}
    try:
        for store in TARGET_STORES:
            rows=_catalog_rows(conn,store); hydrated=[r for r in rows if str(r["fetch_status"] or "").upper()=="OK"]
            per_term={}; union={}
            for term in search_terms:
                wanted=set(_catalog_tokens(term)); hits=[]
                for row in rows:
                    if wanted and wanted.issubset(_catalog_row_tokens(row)): hits.append(row); union[row["url"]]=row
                per_term[term]={"required_tokens":sorted(wanted),"candidate_count":len(hits),
                    "candidates":[_catalog_compact_row(dict(r)) for r in hits[:max_candidates]]}
            union_rows=list(union.values()); queue=_catalog_queue_state(conn,store,[r["url"] for r in union_rows[:max_candidates]])
            result["stores"][store]={"active_catalog_urls":len(rows),"hydrated_ok":len(hydrated),
                "pending_or_error":len(rows)-len(hydrated),"per_term":per_term,
                "union_candidate_count":len(union_rows),
                "union_candidates":[_catalog_compact_row(dict(r)) for r in union_rows[:max_candidates]],
                "hydration_queue_for_candidates":list(queue.values())[:max_candidates],
                "diagnosis":"CATALOG_MATCH_FOUND" if union_rows else "NO_CATALOG_MATCH"}
    finally: conn.close()
    result["elapsed_sec"]=round(time.monotonic()-started,3)
    return result


# ---------------------------------------------------------------------------
# NEW: Deloox scraper -> store_urls -> hydration_queue -> store_products
# Strictly read-only. It executes _discover() in memory, then only SELECTs
# the corresponding SQLite rows. No inserts, updates, hydration, matcher,
# production search, cache invalidation or resync.
# ---------------------------------------------------------------------------
@router.get("/diagnose-deloox-catalog-bridge")
def diagnose_deloox_catalog_bridge(q: str = Query("Hawas"), max_urls: int = Query(80, ge=1, le=200)):
    started = time.monotonic()
    result = {
        "diagnostic": "deloox-catalog-bridge-read-only-v1",
        "ok": True,
        "store": "Deloox",
        "query": q,
        "purpose": "read-only trace: deployed Deloox _discover() -> store_urls -> hydration_queue -> store_products",
        "writes": False,
        "resync": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "hydration_started": False,
        "database_written": False,
    }
    session = None
    try:
        from scrapers.deloox import scraper
        session = requests.Session()
        discovered = scraper._discover(session, str(q or "").strip() or "Hawas")
        discovered = list(dict.fromkeys(discovered or []))[:max_urls]
        result["discovery"] = {
            "count": len(discovered),
            "urls": discovered,
        }
    except Exception as exc:
        result["ok"] = False
        result["stage"] = "scraper_discovery"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        if session:
            session.close()
        return result
    finally:
        if session:
            session.close()

    try:
        from catalog_engine import db
        conn = db()
    except Exception as exc:
        result["ok"] = False
        result["stage"] = "database_open"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["elapsed_sec"] = round(time.monotonic() - started, 3)
        return result

    try:
        urls = discovered
        if not urls:
            result["bridge"] = {"discovered_count": 0}
            return result

        ph = ",".join("?" for _ in urls)

        store_rows = conn.execute(
            f"""SELECT url,active,slug,lastmod,discovered_at
                FROM store_urls
                WHERE store=? AND url IN ({ph})""",
            ("deloox", *urls),
        ).fetchall()
        store_map = {r["url"]: dict(r) for r in store_rows}

        queue_rows = conn.execute(
            f"""SELECT url,state,attempts,available_at,leased_until,
                       last_error,last_http_status,last_started_at,last_finished_at
                FROM hydration_queue
                WHERE store=? AND url IN ({ph})""",
            ("deloox", *urls),
        ).fetchall()
        queue_map = {r["url"]: dict(r) for r in queue_rows}

        product_rows = conn.execute(
            f"""SELECT url,name,brand,fetch_status,fetched_at,price,currency,
                       availability,sku,gtin
                FROM store_products
                WHERE store=? AND url IN ({ph})""",
            ("deloox", *urls),
        ).fetchall()
        product_map = {r["url"]: dict(r) for r in product_rows}

        stages = {
            "discovered": len(urls),
            "store_urls_present": sum(1 for u in urls if u in store_map),
            "store_urls_missing": sum(1 for u in urls if u not in store_map),
            "store_urls_active": sum(1 for u in urls if store_map.get(u, {}).get("active") == 1),
            "hydration_queue_present": sum(1 for u in urls if u in queue_map),
            "hydration_done": sum(1 for u in urls if str(queue_map.get(u, {}).get("state", "")).upper() == "DONE"),
            "hydration_processing": sum(1 for u in urls if str(queue_map.get(u, {}).get("state", "")).upper() == "PROCESSING"),
            "hydration_pending": sum(1 for u in urls if str(queue_map.get(u, {}).get("state", "")).upper() == "PENDING"),
            "hydration_error": sum(1 for u in urls if str(queue_map.get(u, {}).get("state", "")).upper() in {"ERROR", "DEAD"}),
            "store_products_present": sum(1 for u in urls if u in product_map),
            "store_products_ok": sum(1 for u in urls if str(product_map.get(u, {}).get("fetch_status", "")).upper() == "OK"),
        }

        per_url = []
        for u in urls:
            s = store_map.get(u)
            h = queue_map.get(u)
            p = product_map.get(u)
            if u not in store_map:
                bottleneck = "MISSING_FROM_STORE_URLS"
            elif not s.get("active"):
                bottleneck = "STORE_URL_INACTIVE"
            elif u not in queue_map:
                bottleneck = "MISSING_FROM_HYDRATION_QUEUE"
            elif str(h.get("state","")).upper() in {"ERROR","DEAD"}:
                bottleneck = "HYDRATION_ERROR"
            elif str(h.get("state","")).upper() in {"PENDING","PROCESSING"}:
                bottleneck = "HYDRATION_NOT_FINISHED"
            elif u not in product_map:
                bottleneck = "MISSING_FROM_STORE_PRODUCTS"
            elif str(p.get("fetch_status","")).upper() != "OK":
                bottleneck = "STORE_PRODUCT_NOT_OK"
            else:
                bottleneck = "STORE_PRODUCT_OK"
            per_url.append({
                "url": u,
                "store_url": s,
                "hydration": h,
                "store_product": p,
                "bottleneck": bottleneck,
            })

        counts = {}
        for item in per_url:
            counts[item["bottleneck"]] = counts.get(item["bottleneck"], 0) + 1

        result["bridge"] = {
            "stages": stages,
            "bottleneck_counts": counts,
            "per_url": per_url,
            "diagnosis": (
                "BRIDGE_COMPLETE_TO_STORE_PRODUCTS"
                if stages["store_products_ok"] == stages["discovered"]
                else "BRIDGE_STOPS_BEFORE_OR_AT_STORE_PRODUCTS"
            ),
        }
        return result
    except Exception as exc:
        result["ok"] = False
        result["stage"] = "read_only_catalog_selects"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        conn.close()
        result["elapsed_sec"] = round(time.monotonic() - started, 3)

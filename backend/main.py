from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib, json, os, signal, subprocess, sys, threading, time, uuid
try:
    from product_matcher import ProductMatcher
except Exception as exc:
    ProductMatcher = None
    print(f'ProductMatcher unavailable: {type(exc).__name__}: {exc}', flush=True)
from pathlib import Path
APP_VERSION = '4.1-linear-store-contract'
app = FastAPI(title='ScentHunter API', version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

STORES = ['bplatz','deloox','parfumcity','parfumzentrum','perfumemarket','sabina','orioudh','easycosmetic']
STORE_LABELS = {'bplatz':'Bplatz','deloox':'Deloox','parfumcity':'ParfumCity','parfumzentrum':'ParfumZentrum','perfumemarket':'PerfumeMarket','sabina':'Sabina','orioudh':'Orioudh','easycosmetic':'Easycosmetic'}
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / 'frontend' / 'index.html'
PRODUCT_CATALOG_PATH = BASE_DIR / 'product_catalog.json'
FAMILY_REGISTRY_PATH = BASE_DIR / 'family_registry.json'

LIGHTWEIGHT_STORES = ['bplatz','parfumcity','parfumzentrum','perfumemarket','orioudh','easycosmetic']
NETWORK_HEAVY_STORES = ['deloox']
BROWSER_STORES = ['sabina']
LIGHT_WORKERS = 2
NETWORK_WORKERS = 1
BROWSER_WORKERS = 1
STORE_TIMEOUT_SECONDS = 60.0
STORE_TIMEOUTS = {'bplatz':60.0,'deloox':75.0,'parfumcity':60.0,'parfumzentrum':60.0,'perfumemarket':60.0,'sabina':70.0,'orioudh':60.0,'easycosmetic':60.0}
JOB_TIMEOUT_SECONDS = 125.0
LIGHT_SEMAPHORE = threading.Semaphore(LIGHT_WORKERS)
NETWORK_SEMAPHORE = threading.Semaphore(NETWORK_WORKERS)
BROWSER_SEMAPHORE = threading.Semaphore(BROWSER_WORKERS)

def _safe_float(value):
    try:
        if value is None or value == '': return None
        return float(value)
    except (TypeError, ValueError): return None

def _normalise_store(value, fallback):
    text = str(value or fallback).strip().lower()
    return {'bplatz.de':'bplatz','parfum city':'parfumcity','parfum zentrum':'parfumzentrum','parfum-zentrum':'parfumzentrum','perfume market':'perfumemarket','orioudh.com':'orioudh'}.get(text, text)

def _load_product_matcher():
    if ProductMatcher is None:
        return None

    try:
        with open(PRODUCT_CATALOG_PATH, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)

        if isinstance(payload, dict):
            catalog = payload
            product_count = len(payload.get("products") or [])
        elif isinstance(payload, list):
            catalog = payload
            product_count = len(payload)
        else:
            catalog = []
            product_count = 0

        if not product_count:
            print('PRODUCT_MATCHER: catalog empty; identity matching disabled', flush=True)
            return None

        # product_catalog.json remains the primary identity source.
        # family_registry.json only supplements registered legacy families.
        family_registry = None
        if FAMILY_REGISTRY_PATH.exists():
            with open(FAMILY_REGISTRY_PATH, 'r', encoding='utf-8') as handle:
                family_registry = json.load(handle)

        return ProductMatcher(
            catalog=catalog,
            family_registry=family_registry,
        )
    except Exception as exc:
        print(
            f'PRODUCT_MATCHER_INIT_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return None

PRODUCT_MATCHER = _load_product_matcher()

def _identity_scope(query):
    if PRODUCT_MATCHER is None:
        return []
    try:
        return PRODUCT_MATCHER.build_identity_scope(str(query or "").strip())
    except Exception as exc:
        print(
            f'PRODUCT_IDENTITY_SCOPE_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return []

def _resolve_offer_identity(result, query):
    """Resolve one raw retailer offer through ProductMatcher."""
    if not isinstance(result, dict):
        return None
    output = dict(result)
    if PRODUCT_MATCHER is None:
        output.update({"_match_status": "unresolved", "catalog_id": None, "canonical_name": None})
        return output

    try:
        scope = PRODUCT_MATCHER.build_query_scope(query)
        match = PRODUCT_MATCHER.match_offer(offer=output, query_scope=scope)
    except Exception as exc:
        print(f"PRODUCT_MATCHER_MATCH_ERROR: {type(exc).__name__}: {exc}", flush=True)
        output.update({"_match_status": "unresolved", "catalog_id": None, "canonical_name": None, "_match_error": f"{type(exc).__name__}: {exc}"})
        return output

    if not isinstance(match, dict):
        output.update({"_match_status": "unresolved", "catalog_id": None, "canonical_name": None})
        return output

    status = str(match.get("status") or "unresolved").strip().lower()
    if status == "rejected":
        return None

    output["_match_status"] = status
    if status != "matched":
        output.update({"catalog_id": None, "brand": None, "family": None, "variant": None, "canonical_name": None})
        return output

    for key in (
        "catalog_id", "family_id", "family_name", "brand", "family",
        "variant", "canonical_name", "match_method", "match_score",
        "confidence", "matched_alias", "size_ml", "variant_id",
        "canonical_image",
    ):
        if key in match:
            output[key] = match.get(key)
    output["match_confidence"] = match.get("confidence")
    return output

def clean_result(item, store):
    """
    Normalize retailer/commercial data only.

    No catalog identity is assigned here.
    """
    if not isinstance(item, dict):
        return None

    result = dict(item)

    machine_store = _normalise_store(
        result.get("store") or result.get("shop"),
        store,
    )

    raw_name = str(
        result.get("name")
        or result.get("title")
        or ""
    ).strip()

    raw_brand = str(
        result.get("brand")
        or result.get("manufacturer")
        or ""
    ).strip()

    # Preserve retailer values before any harmless technical cleanup.
    result["_raw_name"] = raw_name
    result["_raw_brand"] = raw_brand

    # Keep the retailer's raw name untouched. Identity belongs to ProductMatcher.

    result["store"] = STORE_LABELS.get(
        machine_store,
        machine_store,
    )
    result["shop"] = STORE_LABELS.get(
        machine_store,
        machine_store,
    )

    if "available" not in result and "in_stock" in result:
        result["available"] = bool(result.get("in_stock"))

    if result.get("size_ml") in (None, ""):
        for key in ("volume_ml", "format_ml", "size"):
            value = result.get(key)

            if value in (None, ""):
                continue

            parsed = _safe_float(value)

            if parsed is not None:
                result["size_ml"] = parsed
                break

    if "price_num" not in result:
        parsed = _safe_float(result.get("price"))

        if parsed is not None:
            result["price_num"] = parsed

    return result

def result_key(item):
    store = _normalise_store(item.get('store') or item.get('shop'), '')
    url = str(item.get('url') or item.get('product_url') or '').strip().lower()
    product_id = str(item.get('store_product_id') or item.get('product_id') or item.get('sku') or '').strip().lower()
    name = ' '.join(str(item.get('name') or item.get('title') or '').split()).lower()
    size = _safe_float(item.get('size_ml'))
    return (store, url or product_id or name, round(size,3) if size is not None else '')

def dedupe_results(results, diagnostics=None):
    """Deduplicate offers; optionally record every actual DROP decision."""
    seen = {}
    output = []
    for index, item in enumerate(results):
        key = result_key(item)
        if key not in seen:
            seen[key] = {"index": index, "item": item}
            output.append(item)
            continue
        if diagnostics is not None:
            keeper = seen[key]["item"]
            diagnostics.append({
                "action": "DROP",
                "reason": "duplicate_dedupe_key",
                "dedupe_key": [key[0], key[1], key[2]],
                "dropped": {
                    "store": item.get("store") or item.get("shop"),
                    "url": item.get("url") or item.get("product_url"),
                    "product_id": item.get("store_product_id") or item.get("product_id") or item.get("sku"),
                    "sku": item.get("sku"),
                    "name": item.get("name") or item.get("title"),
                    "size_ml": item.get("size_ml"),
                    "price": item.get("price"),
                    "price_num": item.get("price_num"),
                    "catalog_id": item.get("catalog_id"),
                    "canonical_name": item.get("canonical_name"),
                    "raw_name": item.get("_raw_name"),
                },
                "kept": {
                    "store": keeper.get("store") or keeper.get("shop"),
                    "url": keeper.get("url") or keeper.get("product_url"),
                    "product_id": keeper.get("store_product_id") or keeper.get("product_id") or keeper.get("sku"),
                    "sku": keeper.get("sku"),
                    "name": keeper.get("name") or keeper.get("title"),
                    "size_ml": keeper.get("size_ml"),
                    "price": keeper.get("price"),
                    "price_num": keeper.get("price_num"),
                    "catalog_id": keeper.get("catalog_id"),
                    "canonical_name": keeper.get("canonical_name"),
                    "raw_name": keeper.get("_raw_name"),
                },
            })
    return output

def _public_offer(item):
    """
    Return only commercial retailer data.
    """
    canonical_name = item.get("canonical_name") or item.get("name") or item.get("title")
    canonical_brand = item.get("brand") or item.get("canonical_brand") or item.get("manufacturer")

    return {
        # Canonical identity is deliberately repeated on every public offer.
        # The frontend can therefore flatten offers without losing the product
        # identity that the central matcher already resolved.
        "catalog_id": item.get("catalog_id"),
        "brand": canonical_brand,
        "name": canonical_name,
        "canonical_name": item.get("canonical_name") or canonical_name,
        "family": item.get("family"),
        "variant": item.get("variant"),
        "store": item.get("store"),
        "shop": item.get("shop"),
        "price": item.get("price"),
        "price_num": item.get("price_num"),
        "format": item.get("format"),
        "size_ml": item.get("size_ml"),
        "variant_id": item.get("variant_id"),
        "url": item.get("url") or item.get("product_url"),
        "retailer_image": item.get("image") or item.get("image_url"),
        "available": item.get("available"),
        "raw_name": item.get("_raw_name")
            or item.get("name")
            or item.get("title"),
        "raw_brand": item.get("_raw_brand")
            or item.get("brand")
            or item.get("manufacturer"),
    }

def _aggregate_identity_results(offers):
    """
    Group matched offers by catalog_id.

    Unresolved offers are preserved separately.
    """
    groups = {}
    unresolved = []

    for offer in offers:
        if not isinstance(offer, dict):
            continue

        status = str(
            offer.get("_match_status")
            or "unresolved"
        ).lower()

        if status == "matched" and offer.get("catalog_id"):
            catalog_id = str(
                offer.get("catalog_id")
            ).strip()

            if catalog_id not in groups:
                groups[catalog_id] = {
                    "catalog_id": catalog_id,
                    "brand": offer.get("brand"),
                    "name": offer.get("canonical_name") or offer.get("name"),
                    "family": offer.get("family"),
                    "variant": offer.get("variant"),
                    "canonical_name": offer.get(
                        "canonical_name"
                    ),
                    "image": offer.get("canonical_image") or "",
                    "offers": [],
                }

            groups[catalog_id]["offers"].append(
                _public_offer(offer)
            )

        elif status == "unresolved":
            unresolved.append(
                _public_offer(offer)
            )

    result = list(groups.values())

    for group in result:
        group["offers"] = sorted(
            group["offers"],
            key=lambda item: (
                item.get("price_num")
                if item.get("price_num") is not None
                else 999999.0
            ),
        )

    result.sort(
        key=lambda group: (
            group.get("canonical_name")
            or ""
        ).lower()
    )

    return result, unresolved

def _empty_report(store, status='error', elapsed=0.0, error=None):
    return {
        'store': store,
        'status': status,
        'elapsed': round(elapsed, 3),
        'count': 0,
        'results': [],
        'error': error,
        'attempts': 0,
        'verified': False,
    }

def load_scraper(store): return importlib.import_module(f'scrapers.{store}.scraper')

WORKER_CODE = r'''
import importlib, json, sys
store=sys.argv[1]; query=sys.argv[2]
def emit(event, **payload):
    print(json.dumps({'event':event, **payload},ensure_ascii=False,default=str),flush=True)
try:
    module=importlib.import_module(f'scrapers.{store}.scraper')
    stream=getattr(module,'search_stream',None)
    if callable(stream):
        rows=[]
        def on_result(row):
            if isinstance(row,dict):
                rows.append(row); emit('result',row=row)
        returned=stream(query,on_result)
        if returned is not None:
            try:
                for row in returned:
                    if isinstance(row,dict): emit('result',row=row); rows.append(row)
            except TypeError: pass
        emit('done',count=len(rows),streaming=True)
    else:
        search=getattr(module,'search',None)
        if not callable(search): raise RuntimeError(f'scraper {store} non espone search(query)')
        raw=search(query)
        if raw is None: rows=[]
        elif isinstance(raw,list): rows=raw
        elif isinstance(raw,tuple): rows=list(raw)
        else:
            try: rows=list(raw)
            except TypeError: rows=[]
        for row in rows:
            if isinstance(row,dict): emit('result',row=row)
        emit('done',count=len(rows),streaming=False)
except BaseException as exc:
    emit('error',error=f'{type(exc).__name__}: {exc}')
    raise SystemExit(1)
'''

def _kill_process_tree(process):
    try:
        if process.poll() is not None: return
        if os.name != 'nt': os.killpg(process.pid, signal.SIGKILL)
        else: process.kill()
    except Exception:
        try: process.kill()
        except Exception: pass

def _run_store_subprocess_once(store, query, on_result=None, timeout_override=None):
    started=time.monotonic(); timeout=(float(timeout_override) if timeout_override is not None else STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS))
    env=os.environ.copy(); current=env.get('PYTHONPATH',''); env['PYTHONPATH']=str(BASE_DIR)+(os.pathsep+current if current else '')
    process=None; rows=[]; worker_error=None
    try:
        # IMPORTANT: do not use blocking readline() here.
        # Under concurrent load a worker can stay silent for a while; a
        # blocking readline() would then prevent the individual store
        # timeout from being checked. Use select/os.read so the timeout
        # remains authoritative.
        process=subprocess.Popen([sys.executable,'-u','-c',WORKER_CODE,store,query],cwd=str(BASE_DIR),env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=False,bufsize=0,start_new_session=(os.name!='nt'))
        deadline=time.monotonic()+timeout
        stdout_buffer=b''

        while True:
            remaining=deadline-time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args,timeout)

            chunk=b''
            if process.stdout is not None:
                if os.name != 'nt':
                    import select
                    ready,_,_=select.select(
                        [process.stdout],
                        [],
                        [],
                        min(0.25, remaining),
                    )
                    if ready:
                        try:
                            chunk=os.read(process.stdout.fileno(),65536)
                        except (BlockingIOError,OSError):
                            chunk=b''
                else:
                    # Fly.io runs Linux; this branch is retained for
                    # portability on Windows.
                    try:
                        chunk=process.stdout.read1(65536)
                    except (AttributeError,BlockingIOError):
                        chunk=b''

            if chunk:
                stdout_buffer += chunk

                while b'\n' in stdout_buffer:
                    raw_line,stdout_buffer=stdout_buffer.split(b'\n',1)

                    try:
                        event=json.loads(
                            raw_line.decode('utf-8','replace').strip()
                        )
                    except (json.JSONDecodeError,UnicodeDecodeError):
                        continue

                    if not isinstance(event,dict):
                        continue

                    kind=event.get('event')

                    if kind == "result" and isinstance(event.get("row"), dict):
                        prepared = clean_result(event["row"], store)
                        if prepared is None:
                            continue

                        resolved = _resolve_offer_identity(
                            prepared,
                            query,
                        )
                        if resolved is None:
                            continue

                        rows.append(resolved)

                        if callable(on_result):
                            on_result(resolved)

                    elif kind=='error':
                        worker_error=str(
                            event.get('error') or 'worker_error'
                        )

            if process.poll() is not None:
                # Drain bytes already available after process exit.
                if process.stdout is not None and os.name != 'nt':
                    try:
                        while True:
                            tail=os.read(process.stdout.fileno(),65536)
                            if not tail:
                                break
                            stdout_buffer += tail
                    except (BlockingIOError,OSError):
                        pass
                break

        # A worker normally ends each event with a newline. If a final
        # partial line exists, try to decode it as a last event.
        if stdout_buffer.strip():
            try:
                event=json.loads(
                    stdout_buffer.decode('utf-8','replace').strip()
                )
            except (json.JSONDecodeError,UnicodeDecodeError):
                event=None

            if isinstance(event,dict) and event.get('event')=='error':
                worker_error=str(
                    event.get('error') or 'worker_error'
                )

        rc=process.wait(timeout=1); elapsed=round(time.monotonic()-started,3)
        if rc!=0 or worker_error: return {'store':store,'status':'error','elapsed':elapsed,'count':len(rows),'results':rows,'error':worker_error or f'worker_exit_{rc}'}
        return {'store':store,'status':'ok' if rows else 'empty','elapsed':elapsed,'count':len(rows),'results':rows,'error':None}
    except subprocess.TimeoutExpired:
        if process is not None:
            _kill_process_tree(process)
            try: process.communicate(timeout=2)
            except Exception: pass
        return _empty_report(store,elapsed=round(time.monotonic()-started,3),error=f'store_timeout_{timeout:.0f}s')
    except Exception as exc:
        if process is not None:
            _kill_process_tree(process)
            try: process.communicate(timeout=1)
            except Exception: pass
        return _empty_report(store,elapsed=round(time.monotonic()-started,3),error=f'{type(exc).__name__}: {exc}')


def _run_store_subprocess(store, query, on_result=None):
    """
    Execute one store search with one automatic retry when the scraper
    returns no rows without an explicit error.

    An empty result is therefore never trusted after a single transient
    attempt. The scraper remains responsible for actual discovery; Main only
    supervises execution and records whether the store was verified.
    """
    first = _run_store_subprocess_once(
        store,
        query,
        on_result=on_result,
    )

    if first.get("status") != "empty":
        first["attempts"] = 1
        first["verified"] = first.get("status") == "ok"
        return first

    # A second independent attempt protects against intermittent HTTP,
    # anti-bot, DNS, session and upstream-search failures. We deliberately
    # do not label the first empty response as "no match" yet.
    print(
        f"STORE RETRY store={store} query={query!r} reason=empty_first_attempt",
        flush=True,
    )

    base_timeout = STORE_TIMEOUTS.get(
        store,
        STORE_TIMEOUT_SECONDS,
    )
    retry_timeout = max(
        12.0,
        min(
            base_timeout * 0.5,
            35.0,
        ),
    )
    second = _run_store_subprocess_once(
        store,
        query,
        on_result=on_result,
        timeout_override=retry_timeout,
    )
    second["attempts"] = 2
    second["first_attempt_status"] = "empty"

    if second.get("status") == "empty":
        # Only after two completed empty attempts do we call the result a
        # genuine no-match. This is still a verified live response, just with
        # zero matching products.
        second["status"] = "no_match"
        second["verified"] = True
        second["error"] = None
        return second

    second["verified"] = second.get("status") == "ok"
    return second

def _run_controlled_store(store,query,on_report,on_result=None):
    print(f'STORE START store={store} query={query!r}',flush=True)
    semaphore=LIGHT_SEMAPHORE; lane='light'
    if store in BROWSER_STORES: semaphore=BROWSER_SEMAPHORE; lane='browser'
    elif store in NETWORK_HEAVY_STORES: semaphore=NETWORK_SEMAPHORE; lane='network'
    wait=time.monotonic()
    if semaphore is not None:
        if not semaphore.acquire(timeout=JOB_TIMEOUT_SECONDS):
            report=_empty_report(store,error=f'{lane}_lane_unavailable')
            print(f'STORE TIMEOUT store={store} timeout=lane_wait',flush=True); on_report(report); return
        waited=round(time.monotonic()-wait,3)
        if waited>.1: print(f'STORE QUEUED store={store} lane={lane} waited={waited}',flush=True)
    try: report=_run_store_subprocess(store,query,on_result=on_result)
    finally:
        if semaphore is not None: semaphore.release()
    if report.get('status')=='error':
        if str(report.get('error','')).startswith('store_timeout_'): print(f"STORE TIMEOUT store={store} timeout={report['error']}",flush=True)
        else: print(f"STORE ERROR store={store} error={report.get('error')}",flush=True)
    print(f"STORE END store={store} status={report.get('status')} elapsed={report.get('elapsed')} count={report.get('count')}",flush=True)
    on_report(report)

def collect_store_reports_isolated(query,stores,on_report=None,on_result=None):
    requested=list(stores); reports={}; lock=threading.Lock(); threads=[]
    def publish(report):
        with lock: reports[report['store']]=report
        if callable(on_report): on_report(report)
    for store in requested:
        t=threading.Thread(target=_run_controlled_store,args=(store,query,publish,on_result),daemon=True,name=f'scenthunter-store-{store}')
        t.start(); threads.append(t)
    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in threads: t.join(timeout=max(0.0,deadline-time.monotonic()))
    unfinished=[t.name.rsplit('scenthunter-store-',1)[-1] for t in threads if t.is_alive()]
    if unfinished:
        print(f'SEARCH SUPERVISORS STILL RUNNING stores={unfinished}',flush=True)
        with lock:
            for store in unfinished: reports.setdefault(store,_empty_report(store,elapsed=JOB_TIMEOUT_SECONDS,error='job_timeout'))
    return [reports[s] for s in requested if s in reports]

JOBS={}; JOBS_LOCK=threading.Lock()

def _new_job(query):
    job_id=uuid.uuid4().hex
    with JOBS_LOCK: JOBS[job_id] = {
    "job_id": job_id,
    "query": query,
    "started_at": time.time(),
    "completed": False,

    # Individual deduplicated commercial offers.
    "offers": [],

    # Canonical grouped products exposed by the API.
    "results": [],

    # Offers that were not identifiable with enough certainty.
    "unresolved_offers": [],

    "comparisons": [],
    "errors": {},
    "stores": {},
}

    return job_id

def _snapshot(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job:
            return {
                "job_id": job_id,
                "query": "",
                "completed": True,
                "status": "completed",
                "count": 0,
                "offer_count": 0,
                "results": [],
                "unresolved_offers": [],
                "identity_scope": [],
                        "errors": {
                    "job": "job_not_found"
                },
                "stores": {},
            }

        results = list(
            job.get("results", [])
        )

        offers = list(
            job.get("offers", [])
        )

        return {
            "job_id": job["job_id"],
            "query": job["query"],
            "completed": job["completed"],
            "status": (
                "completed"
                if job["completed"]
                else "searching"
            ),
            "count": len(results),
            "offer_count": len(offers),
            "results": results,
            "unresolved_offers": list(
                job.get("unresolved_offers", [])
            ),
            "identity_scope": _identity_scope(job["query"]),
            "errors": dict(
                job.get("errors", {})
            ),
             "stores": dict(
                job.get("stores", {})
            ),
            "dedupe_diagnostics": list(
                job.get("dedupe_diagnostics", [])
            ),
        }

def _publish_result(job_id, row):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job or job.get("completed"):
            return

        if not isinstance(row, dict):
            return

        job.setdefault("offers", [])
        job["offers"].append(row)
        job["offers"] = dedupe_results(
            job["offers"],
            job.setdefault("dedupe_diagnostics", []),
        )

        grouped, unresolved = (
            _aggregate_identity_results(
                job["offers"]
            )
        )

        job["results"] = grouped
        job["unresolved_offers"] = unresolved

        print(
            "SEARCH PUBLISH RESULT "
            f"job={job_id} "
            f"store={row.get('store')} "
            f"groups={len(grouped)} "
            f"offers={len(job['offers'])}",
            flush=True,
        )

def _publish_store(job_id, report):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

        if not job or job.get("completed"):
            return

        store = report["store"]

        job["stores"][store] = {
            "status": report["status"],
            "verified": bool(report.get("verified")),
            "attempts": int(report.get("attempts") or 0),
            "elapsed": report["elapsed"],
            "count": report["count"],
        }

        if report.get("error"):
            job["errors"][store] = report["error"]

        for item in report.get("results", []):
            if not isinstance(item, dict):
                continue

            job.setdefault("offers", [])
            job["offers"].append(item)

        job["offers"] = dedupe_results(
            job.get("offers", []),
            job.setdefault("dedupe_diagnostics", []),
        )

        grouped, unresolved = (
            _aggregate_identity_results(
                job["offers"]
            )
        )

        job["results"] = grouped
        job["unresolved_offers"] = unresolved

        print(
            "SEARCH PUBLISH "
            f"job={job_id} "
            f"store={store} "
            f"groups={len(grouped)} "
            f"offers={len(job['offers'])}",
            flush=True,
        )

def _run_job(job_id,query):
    started=time.monotonic(); print(f'SEARCH START job={job_id} query={query!r}',flush=True)
    collect_store_reports_isolated(query,STORES,on_report=lambda r:_publish_store(job_id,r),on_result=lambda row:_publish_result(job_id,row))
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if job:
        job["offers"] = dedupe_results(
            job.get("offers", []),
            job.setdefault("dedupe_diagnostics", []),
        )

        grouped, unresolved = (
            _aggregate_identity_results(
                job["offers"]
            )
        )

        job["results"] = grouped
        job["unresolved_offers"] = unresolved
        job["completed"] = True
        job["elapsed"] = round(
            time.monotonic() - started,
            3,
        )

        elapsed = job["elapsed"]
        total = len(job["results"])
    else:
        elapsed = round(
            time.monotonic() - started,
            3,
        )
        total = 0

    print(f'SEARCH END job={job_id} elapsed={elapsed} total={total}',flush=True)

@app.get('/',include_in_schema=False)
def root():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'app':'ScentHunter','status':'running','architecture':APP_VERSION,'error':'frontend/index.html not found'}

@app.get('/health')
def health():
    return {'status':'healthy','architecture':APP_VERSION,'stores':STORES,'lightweight_stores':LIGHTWEIGHT_STORES,'network_heavy_stores':NETWORK_HEAVY_STORES,'browser_stores':BROWSER_STORES,'light_workers':LIGHT_WORKERS,'network_workers':NETWORK_WORKERS,'browser_workers':BROWSER_WORKERS,'store_timeouts':STORE_TIMEOUTS,'job_timeout':JOB_TIMEOUT_SECONDS}

@app.get('/search-start')
def search_start(q:str):
    query=str(q or '').strip()
    if not query: return {'job_id':'','query':'','completed':True,'status':'completed','count':0,'results':[],'unresolved_offers':[],'identity_scope':[],'comparisons':[],'errors':{},'stores':{}}
    job_id=_new_job(query)
    threading.Thread(target=_run_job,args=(job_id,query),daemon=True,name=f'scenthunter-search-{job_id[:8]}').start()
    return _snapshot(job_id)

@app.get('/search-status/{job_id}')
def search_status_path(job_id:str): return _snapshot(job_id)
@app.get('/search-status')
def search_status_query(job_id:str): return _snapshot(job_id)

@app.get("/search")
def search_perfume(q: str):
    query = str(q or "").strip()

    if not query:
        return {
            "query": "",
            "count": 0,
            "offer_count": 0,
            "results": [],
            "unresolved_offers": [],
            "identity_scope": [],
            "errors": {},
            "stores": {},
            "dedupe_diagnostics": [],
        }

    reports = collect_store_reports_isolated(
        query,
        STORES,
    )

    all_offers = []

    for report in reports:
        for item in report.get(
            "results",
            [],
        ):
            if not isinstance(item, dict):
                continue

            all_offers.append(item)

    dedupe_diagnostics = []
    all_offers = dedupe_results(
        all_offers,
        dedupe_diagnostics,
    )

    grouped, unresolved = (
        _aggregate_identity_results(
            all_offers
        )
    )

    return {
        "query": query,
        "count": len(grouped),
        "offer_count": len(all_offers),
        "results": grouped,
        "unresolved_offers": unresolved,
        "dedupe_diagnostics": dedupe_diagnostics,
        "identity_scope": _identity_scope(query),
        "errors": {
            report["store"]: report["error"]
            for report in reports
            if report.get("error")
        },
        "stores": {
            report["store"]: {
                "status": report["status"],
                "verified": bool(report.get("verified")),
                "attempts": int(report.get("attempts") or 0),
                "count": report["count"],
                "elapsed": report["elapsed"],
            }
            for report in reports
        },
    }

@app.get('/frontend')
def frontend():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'error':'frontend/index.html not found'}

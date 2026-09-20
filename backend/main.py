from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib, json, os, re, signal, subprocess, sys, threading, time, traceback, uuid
try:
    from product_matcher import ProductMatcher
except Exception as exc:
    ProductMatcher = None
    print(f'ProductMatcher unavailable: {type(exc).__name__}: {exc}', flush=True)
from pathlib import Path
APP_VERSION = '3.0-streaming-speed'
app = FastAPI(title='ScentHunter API', version=APP_VERSION)
try:
    from debug_easycosmetic import router as debug_easycosmetic_router
    app.include_router(debug_easycosmetic_router)
except Exception as exc:
    print(f'Easycosmetic debug router unavailable: {type(exc).__name__}: {exc}', flush=True)
try:
    from debug_deloox import router as debug_deloox_router
    app.include_router(debug_deloox_router)
except Exception as exc:
    print(f'Deloox debug router unavailable: {type(exc).__name__}: {exc}', flush=True)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
try:
    from debug_bplatz import router as debug_bplatz_router
    app.include_router(debug_bplatz_router)
except Exception as exc:
    print(f'Bplatz debug router unavailable: {type(exc).__name__}: {exc}', flush=True)
try:
    from debug_sabina import router as debug_sabina_router
    app.include_router(debug_sabina_router)
except Exception as exc:
    print(f'Sabina debug router unavailable: {type(exc).__name__}: {exc}', flush=True)

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


def _prepare_raw_offer(result):
    """
    Normalize only technical/commercial retailer fields.

    This function must not assign catalog identity.
    The retailer name remains RAW in _raw_name.
    """
    if not isinstance(result, dict):
        return None

    output = dict(result)

    raw_name = str(
        output.get("name")
        or output.get("title")
        or ""
    ).strip()

    raw_brand = str(
        output.get("brand")
        or output.get("manufacturer")
        or ""
    ).strip()

    output["_raw_name"] = raw_name
    output["_raw_brand"] = raw_brand

    return output


def _resolve_offer_identity(result, query):
    """
    Resolve one RAW retailer offer through the central ProductMatcher.

    Possible outcomes:
    - matched: catalog identity assigned;
    - rejected: definitely not relevant;
    - unresolved: preserve the commercial offer without inventing identity.
    """
    if not isinstance(result, dict):
        return None

    output = dict(result)

    if PRODUCT_MATCHER is None:
        output["_match_status"] = "unresolved"
        output["catalog_id"] = None
        output["canonical_name"] = None
        return output

    try:
        if PRODUCT_MATCHER._is_non_fragrance_offer(output):
            print(
                "PRODUCT_MATCHER_NON_FRAGRANCE_REJECT: "
                f"name={output.get('_raw_name', '')!r} "
                f"brand={output.get('_raw_brand', '')!r}",
                flush=True,
            )
            return None
    except Exception as exc:
        print(
            "PRODUCT_MATCHER_CATEGORY_FILTER_ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    try:
        query_scope = PRODUCT_MATCHER.build_query_scope(query)

        match = PRODUCT_MATCHER.match_offer(
            offer=output,
            query_scope=query_scope,
        )
    except AttributeError:
        # Temporary compatibility fallback while product_matcher.py
        # is being migrated to the new interface.
        output["_match_status"] = "unresolved"
        output["catalog_id"] = None
        output["canonical_name"] = None
        output["_match_error"] = "new_matcher_interface_missing"
        return output
    except Exception as exc:
        print(
            "PRODUCT_MATCHER_MATCH_ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        output["_match_status"] = "unresolved"
        output["catalog_id"] = None
        output["canonical_name"] = None
        output["_match_error"] = f"{type(exc).__name__}: {exc}"
        return output

    if not isinstance(match, dict):
        output["_match_status"] = "unresolved"
        output["catalog_id"] = None
        output["canonical_name"] = None
        return output

    status = str(
        match.get("status") or "unresolved"
    ).strip().lower()

    if status == "rejected":
        print(
            "PRODUCT_MATCHER_REJECT: "
            f"name={output.get('_raw_name', '')!r} "
            f"reason={match.get('reject_reason')!r}",
            flush=True,
        )
        return None

    output["_match_status"] = status

    if status == "matched":
        output["catalog_id"] = match.get("catalog_id")
        output["brand"] = match.get("brand")
        output["family"] = match.get("family")
        output["variant"] = match.get("variant")
        output["canonical_name"] = match.get("canonical_name")
        output["match_confidence"] = match.get("confidence")
        output["matched_alias"] = match.get("matched_alias")
    else:
        output["catalog_id"] = None
        output["brand"] = None
        output["family"] = None
        output["variant"] = None
        output["canonical_name"] = None

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

    # Easycosmetic login entry is not a product.
    if machine_store == "easycosmetic":
        if raw_name.lower() == "anmelden":
            return None

    # Keep the existing narrow Hawas sample exclusion.
    if (
        machine_store == "parfumcity"
        and "hawas" in raw_name.lower()
        and "sample" in raw_name.lower()
    ):
        return None

    # Keep retailer naming cleanup only as RAW-name cleanup.
    # It does not create canonical identity.
    cleaned_name = raw_name

    if "hawas" in cleaned_name.lower():
        cleaned_name = re.sub(
            r"\s+(?:dames|heren|damen|herren)$",
            "",
            cleaned_name,
            flags=re.IGNORECASE,
        ).strip()

    if cleaned_name:
        result["name"] = cleaned_name

    # Preserve the original source image behavior.
    if machine_store == "parfumcity" and not result.get("image"):
        source = result.get("source")
        if isinstance(source, dict) and source.get("image"):
            result["image"] = source.get("image")

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

    result = _prepare_raw_offer(result)

    return result


def _is_hawas_query(query):
    return 'hawas' in str(query or '').strip().lower()

def _is_hawas_daarej_result(item):
    if not isinstance(item, dict):
        return False
    name = str(item.get('name') or item.get('title') or '').strip().lower()
    return 'daarej' in name

def _keep_hawas_result(item, query):
    if not _is_hawas_query(query):
        return True
    return not _is_hawas_daarej_result(item)

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

def sort_results(results):
    def key(item):
        available=item.get('available'); price=_safe_float(item.get('price_num'))
        rank=2 if available is False else 0 if price is not None else 1
        return rank, price if price is not None else 999999.0
    return sorted(results, key=key)

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
        "url": item.get("url") or item.get("product_url"),
        "image": item.get("image") or item.get("image_url"),
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
                    "image": offer.get("image") or offer.get("image_url"),
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
    return {'store':store,'status':status,'elapsed':round(elapsed,3),'count':0,'results':[],'error':error}

def load_scraper(store): return importlib.import_module(f'scrapers.{store}.scraper')

def run_store(store, query):
    started=time.monotonic()
    try:
        search=getattr(load_scraper(store),'search',None)
        if not callable(search): raise RuntimeError(f'scraper {store} non espone search(query)')
        raw=search(query)
        if store=='parfumzentrum' and not raw:
            time.sleep(.25); raw=search(query)
        rows=[] if raw is None else list(raw) if not isinstance(raw, list) else raw
        cleaned = []

        for item in rows:
            if not isinstance(item, dict):
                continue

            prepared = clean_result(item, store)

            if prepared is None:
                continue

            resolved = _resolve_offer_identity(
                prepared,
                query,
            )

            if resolved is None:
                continue

            cleaned.append(resolved)

        return {'store':store,'status':'ok' if cleaned else 'empty','elapsed':round(time.monotonic()-started,3),'count':len(cleaned),'results':cleaned,'error':None}
    except Exception as exc:
        traceback.print_exc()
        err = str(exc)
        status = 'error'
        code = 'runtime_error'
        return {
            'store': store,
            'status': status,
            'error': err,
            'error_code': code,
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'results': [],
        }

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

def _run_store_subprocess(store, query, on_result=None):
    started=time.monotonic(); timeout=STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS)
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

                while b'\\n' in stdout_buffer:
                    raw_line,stdout_buffer=stdout_buffer.split(b'\\n',1)

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
                "comparisons": [],
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
            "comparisons": list(
                job.get("comparisons", [])
            ),
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

        if not _keep_hawas_result(
            row,
            job.get("query"),
        ):
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
            "elapsed": report["elapsed"],
            "count": report["count"],
        }

        if report.get("error"):
            job["errors"][store] = report["error"]

        for item in report.get("results", []):
            if not isinstance(item, dict):
                continue

            if not _keep_hawas_result(
                item,
                job.get("query"),
            ):
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


def _collect_streaming_for_job(job_id,query,stores):
    reports={}; lock=threading.Lock(); threads=[]
    def publish(report):
        with lock: reports[report['store']]=report
        _publish_store(job_id,report)
    def publish_row(row): _publish_result(job_id,row)
    for store in stores:
        t=threading.Thread(target=_run_controlled_store,args=(store,query,publish,publish_row),daemon=True,name=f'scenthunter-store-{store}')
        t.start(); threads.append(t)
    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in threads: t.join(timeout=max(0.0,deadline-time.monotonic()))
    return [reports[s] for s in stores if s in reports]

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

            if not _keep_hawas_result(
                item,
                query,
            ):
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
                "count": report["count"],
                "elapsed": report["elapsed"],
            }
            for report in reports
        },
    }


@app.get('/test-store')
def test_store(store:str,q:str):
    store=str(store or '').strip().lower(); query=str(q or '').strip()
    if store not in STORES:
        return {'ok':False,'store':store,'query':query,'error':'unknown_store','stores':STORES}

    # Diagnostic endpoint: use the same isolated subprocess path as production.
    report_holder=[]
    done=threading.Event()

    def publish(report):
        report_holder.append(report)
        done.set()

    t=threading.Thread(
        target=_run_controlled_store,
        args=(store,query,publish),
        daemon=True,
        name=f'test-store-{store}',
    )
    t.start()
    done.wait(timeout=STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS)+5)

    report=report_holder[0] if report_holder else _empty_report(
        store,
        error='diagnostic_timeout',
    )
    return {'ok':report['status']!='error','store':store,'query':query,**report}

@app.get('/diagnose-stores')
def diagnose_stores(q:str='Liquid Brun'):
    query=str(q or '').strip()
    if not query: return {'ok':False,'query':'','stores':[],'total_count':0,'architecture':APP_VERSION}
    reports=collect_store_reports_isolated(query,STORES); by_store={r['store']:r for r in reports}; ordered=[by_store[s] for s in STORES if s in by_store]
    return {'ok':True,'architecture':APP_VERSION,'query':query,'stores':ordered,"total_count": sum(
    r.get("count", 0)
    for r in ordered
),
"offer_count": sum(
    r.get("count", 0)
    for r in ordered
),
}

@app.get('/diagnose-sabina')
def diagnose_sabina(q:str='Liquid Brun'):
    query=str(q or '').strip()
    started=time.monotonic()
    report={'ok':True,'architecture':APP_VERSION,'query':query,'elapsed':0.0,'module':{},'direct_search':{},'stream_search':{}}
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        try:
            import sitecustomize as _sitecustomize
            importlib.reload(_sitecustomize)
            report['sitecustomize']={'loaded':True,'module':getattr(_sitecustomize,'__file__',None)}
        except Exception as exc:
            report['sitecustomize']={'loaded':False,'error':f'{type(exc).__name__}: {exc}'}
        module=load_scraper('sabina')
        report['module']={'module':getattr(module,'__file__',None),'BASE_URL':getattr(module,'BASE_URL',None),'BASE':getattr(module,'BASE',None),'_clean':callable(getattr(module,'_clean',None)),'clean':callable(getattr(module,'clean',None)),'search':callable(getattr(module,'search',None)),'search_stream':callable(getattr(module,'search_stream',None))}
        try:
            t=time.monotonic(); raw=module.search(query); rows=[] if raw is None else list(raw) if not isinstance(raw,list) else raw
            report['direct_search']={'elapsed':round(time.monotonic()-t,3),'count':len(rows),'results':[clean_result(x,'sabina') for x in rows if isinstance(x,dict)]}
        except Exception as exc:
            report['direct_search']={'elapsed':round(time.monotonic()-t,3),'count':0,'error':f'{type(exc).__name__}: {exc}'}
        stream=getattr(module,'search_stream',None)
        if callable(stream):
            stream_rows=[]; t=time.monotonic()
            def collect(row):
                if isinstance(row,dict): stream_rows.append(clean_result(row,'sabina'))
            try:
                returned=stream(query,collect)
                if returned is not None:
                    try:
                        for row in returned:
                            if isinstance(row,dict): stream_rows.append(clean_result(row,'sabina'))
                    except TypeError: pass
                report['stream_search']={'elapsed':round(time.monotonic()-t,3),'count':len(stream_rows),'results':stream_rows}
            except Exception as exc:
                report['stream_search']={'elapsed':round(time.monotonic()-t,3),'count':len(stream_rows),'results':stream_rows,'error':f'{type(exc).__name__}: {exc}'}
        else:
            report['stream_search']={'elapsed':0.0,'count':0,'error':'search_stream_missing'}
    except Exception as exc:
        report['ok']=False; report['error']=f'{type(exc).__name__}: {exc}'
    report['elapsed']=round(time.monotonic()-started,3)
    return report

@app.get('/suggest')
def suggest(q:str):
    query=str(q or '').strip()
    if len(query)<2: return {'query':query,'count':0,'suggestions':[]}
    suggestions=[]; seen=set(); reports=collect_store_reports_isolated(query,LIGHTWEIGHT_STORES[:4])
    for report in reports:
        for item in report.get('results',[]):
            name=str(item.get('name') or item.get('title') or '').strip(); brand=str(item.get('brand') or '').strip()
            if not name: continue
            key=f'{brand}|{name}'.lower()
            if key in seen: continue
            seen.add(key); suggestions.append({'brand':brand,'name':name})
            if len(suggestions)>=8: break
        if len(suggestions)>=8: break
    return {'query':query,'count':len(suggestions),'suggestions':suggestions[:8]}

@app.get('/frontend')
def frontend():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'error':'frontend/index.html not found'}

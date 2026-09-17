from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib, json, os, signal, subprocess, sys, threading, time, traceback, uuid
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

def _is_hawas_query(query):
    text = str(query or '').strip().lower()
    return 'hawas' in text

def _is_hawas_daarej_result(item):
    name = str(item.get('name') or item.get('title') or '').strip().lower()
    brand = str(item.get('brand') or item.get('manufacturer') or '').strip().lower()
    return 'daarej' in name and (not brand or 'rasasi' in brand)

def _filter_hawas_results(results, query):
    if not _is_hawas_query(query):
        return list(results or [])
    return [
        item for item in (results or [])
        if isinstance(item, dict) and not _is_hawas_daarej_result(item)
    ]


def _normalise_hawas_name(result, machine_store):
    """Canonicalize only known PerfumeMarket Hawas naming noise."""
    if machine_store != 'perfumemarket' or not isinstance(result, dict):
        return result

    name = str(result.get('name') or result.get('title') or '').strip()
    if not name or 'hawas' not in name.lower():
        return result

    # PerfumeMarket uses E'clat / E’clat / E`clat variants for the same
    # Hawas Eclat product. Normalize only this Hawas family label.
    normalized = re.sub(r"e[`'’‘´]clat", 'Eclat', name, flags=re.IGNORECASE)

    if normalized != name:
        result = dict(result)
        result['name'] = normalized

    return result

def _load_product_matcher():
    if ProductMatcher is None:
        return None

    try:
        with open(PRODUCT_CATALOG_PATH, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)

        if isinstance(payload, dict):
            catalog = payload.get('products') or []
        elif isinstance(payload, list):
            catalog = payload
        else:
            catalog = []

        if not catalog:
            print('PRODUCT_MATCHER: catalog empty; identity matching disabled', flush=True)
            return None

        return ProductMatcher(catalog=catalog)
    except Exception as exc:
        print(
            f'PRODUCT_MATCHER_INIT_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return None


PRODUCT_MATCHER = _load_product_matcher()


def _normalise_easycosmetic_9pm_name(result, machine_store):
    """
    Easycosmetic uses a retailer-specific "9 Collection 9 Pm ..." label for
    the Afnan 9 PM line.

    This is ONLY a source-name normalization. It deliberately does not invoke
    ProductMatcher and does not alter any other store/product. The original
    retailer name is retained in _source_name for diagnostics.
    """
    if machine_store != 'easycosmetic' or not isinstance(result, dict):
        return result

    raw_name = str(
        result.get('name')
        or result.get('title')
        or result.get('product_name')
        or ''
    ).strip()

    if not raw_name:
        return result

    normalized_source_name = re.sub(r'\s+', ' ', raw_name).strip()

    match = re.fullmatch(
        r'(?:afnan\s*[-–—:]\s*)?'
        r'9\s+collection\s+9\s*(?:p\.?\s*m\.?)'
        r'(?:\s+(pour\s+femme|elixir(?:\s+parfum\s+intense)?|night\s+out|rebel))?'
        r'(?:\s+\d+(?:[.,]\d+)?\s*(?:ml|cl))?',
        normalized_source_name,
        flags=re.IGNORECASE,
    )

    if not match:
        return result

    variant = re.sub(r'\s+', ' ', (match.group(1) or '')).strip().lower()

    canonical = 'Afnan - 9 PM'
    if variant == 'pour femme':
        canonical = 'Afnan - 9 PM Pour Femme'
    elif variant.startswith('elixir'):
        canonical = 'Afnan - 9 PM Elixir'
    elif variant == 'night out':
        canonical = 'Afnan - 9 PM Night Out'
    elif variant == 'rebel':
        canonical = 'Afnan - 9 PM Rebel'

    normalized = dict(result)
    normalized.setdefault('_source_name', raw_name)
    normalized['name'] = canonical
    normalized.setdefault('brand', 'Afnan')
    return normalized


def _apply_product_identity(result, query=""):
    """
    Compatibility wrapper kept at the existing call site.

    IMPORTANT: do not activate ProductMatcher here. The central matcher has
    duplicate canonical 9 PM catalog entries and Easycosmetic's "Collection"
    labels are retailer aliases, not catalog identities. Identity matching at
    this point was the regression that removed three of the five 9 PM
    variants. This boundary performs only the narrow Easycosmetic rename.
    """
    if not isinstance(result, dict):
        return result

    machine_store = _normalise_store(
        result.get('store') or result.get('shop'),
        '',
    )
    return _normalise_easycosmetic_9pm_name(result, machine_store)


def clean_result(item, store):
    result = dict(item)
    machine_store = _normalise_store(result.get('store') or result.get('shop'), store)

    raw_name = str(result.get('name') or result.get('title') or '').strip()

    # CHIRURGICO HAWAS:
    # ParfumCity is returning sample listings as normal perfume offers.
    # They are not clickable product offers and must never reach the UI.
    if machine_store == 'parfumcity' and 'sample' in raw_name.lower():
        return None

    # CHIRURGICO HAWAS / PERFUMEMARKET:
    # PerfumeMarket appends the localized gender word "Dames"/"Heren"
    # to Hawas titles. Keep the original source name separately, but expose
    # the canonical Hawas name so the frontend groups it with the real card.
    # This is deliberately limited to Hawas + PerfumeMarket.
    if machine_store == 'perfumemarket' and 'hawas' in raw_name.lower():
        parts = raw_name.rsplit(' ', 1)
        if len(parts) == 2 and parts[1].strip().lower() in ('dames', 'heren'):
            result['name'] = parts[0].strip()

    # Normalize Hawas Eclat punctuation after the Dames/Heren cleanup.
    result = _normalise_hawas_name(result, machine_store)

    result['store'] = STORE_LABELS.get(machine_store, machine_store)
    result['shop'] = STORE_LABELS.get(machine_store, machine_store)
    if 'available' not in result and 'in_stock' in result: result['available'] = bool(result.get('in_stock'))
    if result.get('size_ml') in (None, ''):
        for key in ('volume_ml','format_ml','size'):
            value = result.get(key)
            if value not in (None, ''):
                parsed = _safe_float(value)
                if parsed is not None:
                    result['size_ml'] = parsed; break
    if 'price_num' not in result:
        parsed = _safe_float(result.get('price'))
        if parsed is not None: result['price_num'] = parsed
    return _apply_product_identity(result)

def result_key(item):
    store = _normalise_store(item.get('store') or item.get('shop'), '')
    url = str(item.get('url') or item.get('product_url') or '').strip().lower()
    product_id = str(item.get('store_product_id') or item.get('product_id') or item.get('sku') or '').strip().lower()
    name = ' '.join(str(item.get('name') or item.get('title') or '').split()).lower()
    size = _safe_float(item.get('size_ml'))
    return (store, url or product_id or name, round(size,3) if size is not None else '')

def dedupe_results(results):
    seen=set(); output=[]
    for item in results:
        key=result_key(item)
        if key not in seen: seen.add(key); output.append(item)
    return output

def sort_results(results):
    def key(item):
        available=item.get('available'); price=_safe_float(item.get('price_num'))
        rank=2 if available is False else 0 if price is not None else 1
        return rank, price if price is not None else 999999.0
    return sorted(results, key=key)

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
        cleaned=[cleaned for x in rows if isinstance(x,dict) for cleaned in [clean_result(x,store)] if cleaned is not None]
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
        process=subprocess.Popen([sys.executable,'-u','-c',WORKER_CODE,store,query],cwd=str(BASE_DIR),env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',errors='replace',bufsize=1,start_new_session=(os.name!='nt'))
        deadline=time.monotonic()+timeout
        while True:
            if time.monotonic() >= deadline: raise subprocess.TimeoutExpired(process.args,timeout)
            line=process.stdout.readline() if process.stdout is not None else ''
            if not line:
                if process.poll() is not None: break
                time.sleep(0.01); continue
            try: event=json.loads(line.strip())
            except json.JSONDecodeError: continue
            if not isinstance(event,dict): continue
            kind=event.get('event')
            if kind=='result' and isinstance(event.get('row'),dict):
                row=clean_result(event['row'],store)
                if row is None:
                    continue
                rows.append(row)
                if callable(on_result): on_result(row)
            elif kind=='error': worker_error=str(event.get('error') or 'worker_error')
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
    with JOBS_LOCK: JOBS[job_id]={'job_id':job_id,'query':query,'started_at':time.time(),'completed':False,'results':[],'comparisons':[],'errors':{},'stores':{}}
    return job_id

def _snapshot(job_id):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job: return {'job_id':job_id,'query':'','completed':True,'status':'completed','count':0,'results':[],'comparisons':[],'errors':{'job':'job_not_found'},'stores':{}}
        return {'job_id':job['job_id'],'query':job['query'],'completed':job['completed'],'status':'completed' if job['completed'] else 'searching','count':len(job['results']),'results':list(job['results']),'comparisons':list(job['comparisons']),'errors':dict(job['errors']),'stores':dict(job['stores'])}

def _publish_result(job_id,row):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'): return
        query=job.get('query','')
        if _is_hawas_query(query) and _is_hawas_daarej_result(row):
            return
        clean=clean_result(row,row.get('store') or row.get('shop') or '')
        if clean is None:
            return
        job['results'].append(clean); job['results']=sort_results(dedupe_results(job['results'])); total=len(job['results'])
    print(f"SEARCH PUBLISH RESULT job={job_id} store={clean.get('store')} total={total}",flush=True)

def _publish_store(job_id,report):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'): return
        store=report['store']; job['stores'][store]={'status':report['status'],'elapsed':report['elapsed'],'count':report['count']}
        if report.get('error'): job['errors'][store]=report['error']
        if report.get('results'):
            filtered=_filter_hawas_results(report['results'],job.get('query',''))
            job['results'].extend(filtered)
        job['results']=sort_results(dedupe_results(job['results'])); total=len(job['results'])
    print(f"SEARCH PUBLISH job={job_id} store={store} count={report.get('count')} total={total}",flush=True)

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

    # CHIRURGICO HAWAS:
    # PerfumeMarket has a real "Hawas for Her" product, but its normal
    # "Hawas" search can omit it. Only for an exact Hawas-family search,
    # perform one bounded fallback against PerfumeMarket. No global matcher
    # or other retailer search logic is changed.
    if _is_hawas_query(query):
        with JOBS_LOCK:
            current_names=[
                str(x.get('name') or '').strip().lower()
                for x in JOBS.get(job_id,{}).get('results',[])
                if isinstance(x,dict)
            ]

        if not any('hawas for her' in n for n in current_names):
            # PerfumeMarket's normal Hawas search can omit the women's
            # product. Try only narrow equivalent queries, stopping as soon
            # as a real Hawas-for-Her result is found.
            for fallback_query in (
                'Hawas for Her',
                'Rasasi Hawas Women',
                'Hawas Women',
            ):
                fallback_reports=collect_store_reports_isolated(
                    fallback_query,
                    ['perfumemarket'],
                    on_report=lambda r:_publish_store(job_id,r),
                    on_result=lambda row:_publish_result(job_id,row),
                )

                with JOBS_LOCK:
                    current_names=[
                        str(x.get('name') or '').strip().lower()
                        for x in JOBS.get(job_id,{}).get('results',[])
                        if isinstance(x,dict)
                    ]

                if any('hawas for her' in n for n in current_names):
                    break

    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if job:
            job['results']=sort_results(dedupe_results(job['results'])); job['completed']=True; job['elapsed']=round(time.monotonic()-started,3); elapsed=job['elapsed']; total=len(job['results'])
        else: elapsed=round(time.monotonic()-started,3); total=0
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
    if not query: return {'job_id':'','query':'','completed':True,'status':'completed','count':0,'results':[],'comparisons':[],'errors':{},'stores':{}}
    job_id=_new_job(query)
    threading.Thread(target=_run_job,args=(job_id,query),daemon=True,name=f'scenthunter-search-{job_id[:8]}').start()
    return _snapshot(job_id)

@app.get('/search-status/{job_id}')
def search_status_path(job_id:str): return _snapshot(job_id)
@app.get('/search-status')
def search_status_query(job_id:str): return _snapshot(job_id)

@app.get('/search')
def search_perfume(q:str):
    query=str(q or '').strip()
    if not query: return {'query':'','count':0,'results':[],'errors':{},'stores':{}}
    reports=collect_store_reports_isolated(query,STORES); all_results=[]
    for report in reports:
        all_results.extend(_filter_hawas_results(report['results'],query))

    if _is_hawas_query(query) and not any(
        'hawas for her' in str(x.get('name') or '').strip().lower()
        for x in all_results if isinstance(x,dict)
    ):
        for fallback_query in ('Hawas for Her', 'Rasasi Hawas Women', 'Hawas Women'):
            fallback_reports=collect_store_reports_isolated(
                fallback_query,
                ['perfumemarket'],
            )
            for report in fallback_reports:
                all_results.extend(_filter_hawas_results(report['results'],query))

            if any(
                'hawas for her' in str(x.get('name') or '').strip().lower()
                for x in all_results if isinstance(x,dict)
            ):
                break

    results=sort_results(dedupe_results(all_results))
    return {'query':query,'count':len(results),'results':results,'errors':{r['store']:r['error'] for r in reports if r.get('error')},'stores':{r['store']:{'status':r['status'],'count':r['count'],'elapsed':r['elapsed']} for r in reports}}

@app.get('/test-store')
def test_store(store:str,q:str):
    store=str(store or '').strip().lower(); query=str(q or '').strip()
    if store not in STORES: return {'ok':False,'store':store,'query':query,'error':'unknown_store','stores':STORES}
    report=run_store(store,query); return {'ok':report['status']!='error','store':store,'query':query,**report}

@app.get('/diagnose-stores')
def diagnose_stores(q:str='Liquid Brun'):
    query=str(q or '').strip()
    if not query: return {'ok':False,'query':'','stores':[],'total_count':0,'architecture':APP_VERSION}
    reports=collect_store_reports_isolated(query,STORES); by_store={r['store']:r for r in reports}; ordered=[by_store[s] for s in STORES if s in by_store]
    return {'ok':True,'architecture':APP_VERSION,'query':query,'stores':ordered,'total_count':sum(r.get('count',0) for r in ordered)}

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

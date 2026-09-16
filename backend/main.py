# ScentHunter main.py
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
for module_name, router_name, label in [
    ('debug_easycosmetic', 'debug_easycosmetic_router', 'Easycosmetic'),
    ('debug_deloox', 'debug_deloox_router', 'Deloox'),
    ('debug_bplatz', 'debug_bplatz_router', 'Bplatz'),
    ('debug_sabina', 'debug_sabina_router', 'Sabina'),
    ('debug_orioudh', 'debug_orioudh_router', 'Orioudh'),
]:
    try:
        module = importlib.import_module(module_name)
        router = getattr(
            module,
            router_name,
            getattr(module, 'router', None),
        )
        if router is None:
            raise AttributeError(
                f'{module_name} does not expose '
                f'{router_name} or router'
            )
        app.include_router(router)
    except Exception as exc:
        print(f'{label} debug router unavailable: {type(exc).__name__}: {exc}', flush=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Deloox runtime diagnostic router is OPTIONAL.
# A diagnostic failure must NEVER crash the production API.
try:
    from debug_deloox_runtime import (
        router as deloox_runtime_debug_router,
    )
    app.include_router(deloox_runtime_debug_router)
    print('DELOOX RUNTIME DEBUG ROUTER: LOADED', flush=True)
except Exception as exc:
    print(
        'DELOOX RUNTIME DEBUG ROUTER: UNAVAILABLE '
        f'{type(exc).__name__}: {exc}',
        flush=True,
    )

# Deloox cap diagnostic router is OPTIONAL.
try:
    from debug_deloox_cap_probe import router as deloox_cap_probe_router
    app.include_router(deloox_cap_probe_router)
    print('DELOOX CAP DEBUG ROUTER: LOADED', flush=True)
except Exception as exc:
    print(
        'DELOOX CAP DEBUG ROUTER: UNAVAILABLE '
        f'{type(exc).__name__}: {exc}',
        flush=True,
    )

STORES = ['bplatz','deloox','parfumcity','parfumzentrum','perfumemarket','sabina','orioudh','easycosmetic']
STORE_LABELS = {'bplatz':'Bplatz','deloox':'Deloox','parfumcity':'ParfumCity','parfumzentrum':'ParfumZentrum','perfumemarket':'PerfumeMarket','sabina':'Sabina','orioudh':'Orioudh','easycosmetic':'Easycosmetic'}
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / 'frontend' / 'index.html'
PRODUCT_CATALOG_PATH = BASE_DIR / 'product_catalog.json'
FAMILY_REGISTRY_PATH = BASE_DIR / 'family_registry.json'
LIGHTWEIGHT_STORES = ['bplatz','parfumcity','parfumzentrum','perfumemarket','orioudh','easycosmetic']
NETWORK_HEAVY_STORES = ['deloox']
BROWSER_STORES = ['sabina']
LIGHT_WORKERS = 6
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
    if ProductMatcher is None: return None
    try:
        with open(PRODUCT_CATALOG_PATH, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        if isinstance(payload, dict): catalog = payload.get('products') or []
        elif isinstance(payload, list): catalog = payload
        else: catalog = []
        if not catalog:
            print('PRODUCT_MATCHER: catalog empty; identity matching disabled', flush=True)
            return None
        family_registry = None
        try:
            with open(FAMILY_REGISTRY_PATH, 'r', encoding='utf-8') as registry_handle:
                family_registry = json.load(registry_handle)
        except Exception as registry_exc:
            print(f'PRODUCT_MATCHER_REGISTRY_LOAD_ERROR: {type(registry_exc).__name__}: {registry_exc}', flush=True)
        return ProductMatcher(catalog=catalog, family_registry=family_registry)
    except Exception as exc:
        print(f'PRODUCT_MATCHER_INIT_ERROR: {type(exc).__name__}: {exc}', flush=True)
        return None

PRODUCT_MATCHER = _load_product_matcher()

def _apply_product_identity(result, query=''):
    """Normalize a retailer offer through ProductMatcher, fail-closed for family queries."""
    if PRODUCT_MATCHER is None or not isinstance(result, dict): return result
    raw_name = str(result.get('name') or result.get('title') or '').strip()
    raw_brand = str(result.get('brand') or result.get('manufacturer') or '').strip()

    requested_family = None
    try:
        resolver = getattr(PRODUCT_MATCHER, '_family_for_query', None)
        if callable(resolver):
            requested_family = resolver(query)
    except Exception as exc:
        print(f'PRODUCT_MATCHER_FAMILY_RESOLVE_ERROR: {type(exc).__name__}: {exc}', flush=True)

    try:
        matched = PRODUCT_MATCHER.match(result, query)
    except Exception as exc:
        print(f'PRODUCT_MATCHER_MATCH_ERROR: {type(exc).__name__}: {exc}', flush=True)
        return None if requested_family is not None else result
    if matched is None: return None
    if not isinstance(matched, dict): return None if requested_family is not None else result
    normalized = dict(matched)

    if requested_family is not None:
        requested_family_id = str(requested_family.get('family_id') or '').strip()
        matched_family_id = str(normalized.get('family_id') or '').strip()
        if not requested_family_id or matched_family_id != requested_family_id:
            print(f'PRODUCT_MATCHER_FAMILY_REJECT: query={query!r} requested_family={requested_family_id!r} matched_family={matched_family_id!r} name={raw_name!r} brand={raw_brand!r}', flush=True)
            return None
        requested_family_brand = str(requested_family.get('brand') or '').strip()
        matched_brand = str(normalized.get('canonical_brand') or normalized.get('brand') or '').strip()
        if requested_family_brand and matched_brand:
            normalise = getattr(PRODUCT_MATCHER, '_norm', None)
            try:
                if callable(normalise):
                    family_brand_key = normalise(requested_family_brand)
                    matched_brand_key = normalise(matched_brand)
                else:
                    family_brand_key = requested_family_brand.casefold()
                    matched_brand_key = matched_brand.casefold()
            except Exception:
                family_brand_key = requested_family_brand.casefold()
                matched_brand_key = matched_brand.casefold()
            if family_brand_key != matched_brand_key:
                print(f'PRODUCT_MATCHER_BRAND_REJECT: query={query!r} requested_brand={requested_family_brand!r} matched_brand={matched_brand!r} family={requested_family_id!r} name={raw_name!r}', flush=True)
                return None

    if raw_name: normalized.setdefault('_source_name', raw_name)
    if raw_brand: normalized.setdefault('_source_brand', raw_brand)
    canonical_name = str(normalized.get('canonical_name') or normalized.get('catalog_variant') or raw_name).strip()
    canonical_brand = str(normalized.get('canonical_brand') or normalized.get('brand') or raw_brand).strip()
    if canonical_name: normalized['name'] = canonical_name
    if canonical_brand: normalized['brand'] = canonical_brand
    return normalized

def clean_result(item, store, query=''):
    result = dict(item)
    machine_store = _normalise_store(result.get('store') or result.get('shop'), store)
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
    return _apply_product_identity(result, query)

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
        cleaned=[cleaned for x in rows if isinstance(x,dict) for cleaned in [clean_result(x,store,query)] if cleaned is not None]
        return {'store':store,'status':'ok' if cleaned else 'empty','elapsed':round(time.monotonic()-started,3),'count':len(cleaned),'results':cleaned,'error':None}
    except Exception as exc:
        traceback.print_exc(); err=str(exc)
        return {'store':store,'status':'error','error':err,'error_code':'runtime_error','elapsed_ms':int((time.monotonic()-started)*1000),'results':[]}

WORKER_CODE = r'''
import importlib, json, sys
store=sys.argv[1]; query=sys.argv[2]
def emit(event, **payload): print(json.dumps({'event':event, **payload},ensure_ascii=False,default=str),flush=True)
try:
    module=importlib.import_module(f'scrapers.{store}.scraper')
    stream=getattr(module,'search_stream',None)
    if callable(stream):
        rows=[]
        def on_result(row):
            if isinstance(row,dict): rows.append(row); emit('result',row=row)
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
    emit('error',error=f'{type(exc).__name__}: {exc}'); raise SystemExit(1)
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
                row=clean_result(event['row'],store,query)
                if row is None: continue
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
            report=_empty_report(store,error=f'{lane}_lane_unavailable'); print(f'STORE TIMEOUT store={store} timeout=lane_wait',flush=True); on_report(report); return
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

def _publish_result(job_id,row,query):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'): return
        clean=clean_result(row,row.get('store') or row.get('shop') or '',query)
        if clean is None: return
        job['results'].append(clean); job['results']=sort_results(dedupe_results(job['results'])); total=len(job['results'])
    print(f"SEARCH PUBLISH RESULT job={job_id} store={clean.get('store')} total={total}",flush=True)

def _publish_store(job_id,report):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'): return
        store=report['store']; job['stores'][store]={'status':report['status'],'elapsed':report['elapsed'],'count':report['count']}
        if report.get('error'): job['errors'][store]=report['error']
        if report.get('results'): job['results'].extend(report['results'])
        job['results']=sort_results(dedupe_results(job['results'])); total=len(job['results'])
    print(f"SEARCH PUBLISH job={job_id} store={store} count={report.get('count')} total={total}",flush=True)

def _collect_streaming_for_job(job_id,query,stores):
    reports={}; lock=threading.Lock(); threads=[]
    def publish(report):
        with lock: reports[report['store']]=report
        _publish_store(job_id,report)
    def publish_row(row): _publish_result(job_id,row,query)
    for store in stores:
        t=threading.Thread(target=_run_controlled_store,args=(store,query,publish,publish_row),daemon=True,name=f'scenthunter-store-{store}')
        t.start(); threads.append(t)
    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in threads: t.join(timeout=max(0.0,deadline-time.monotonic()))
    return [reports[s] for s in stores if s in reports]

def _run_job(job_id,query):
    started=time.monotonic(); print(f'SEARCH START job={job_id} query={query!r}',flush=True)
    collect_store_reports_isolated(query,STORES,on_report=lambda r:_publish_store(job_id,r),on_result=lambda row:_publish_result(job_id,row,query))
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
    job_id=_new_job(query); threading.Thread(target=_run_job,args=(job_id,query),daemon=True,name=f'scenthunter-search-{job_id[:8]}').start(); return _snapshot(job_id)
@app.get('/search-status/{job_id}')
def search_status_path(job_id:str): return _snapshot(job_id)
@app.get('/search-status')
def search_status_query(job_id:str): return _snapshot(job_id)
@app.get('/search')
def search_perfume(q:str):
    query=str(q or '').strip()
    if not query: return {'query':'','count':0,'results':[],'errors':{},'stores':{}}
    reports=collect_store_reports_isolated(query,STORES); all_results=[]
    for report in reports: all_results.extend(report['results'])
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
    query=str(q or '').strip(); started=time.monotonic(); report={'ok':True,'architecture':APP_VERSION,'query':query,'elapsed':0.0,'module':{},'direct_search':{},'stream_search':{}}
    try:
        if str(BASE_DIR) not in sys.path: sys.path.insert(0,str(BASE_DIR))
        try:
            import sitecustomize as _sitecustomize; importlib.reload(_sitecustomize); report['sitecustomize']={'loaded':True,'module':getattr(_sitecustomize,'__file__',None)}
        except Exception as exc: report['sitecustomize']={'loaded':False,'error':f'{type(exc).__name__}: {exc}'}
        module=load_scraper('sabina')
        report['module']={'module':getattr(module,'__file__',None),'BASE_URL':getattr(module,'BASE_URL',None),'BASE':getattr(module,'BASE',None),'_clean':callable(getattr(module,'_clean',None)),'clean':callable(getattr(module,'clean',None)),'search':callable(getattr(module,'search',None)),'search_stream':callable(getattr(module,'search_stream',None))}
        try:
            t=time.monotonic(); raw=module.search(query); rows=[] if raw is None else list(raw) if not isinstance(raw,list) else raw
            report['direct_search']={'elapsed':round(time.monotonic()-t,3),'count':len(rows),'results':[clean_result(x,'sabina',query) for x in rows if isinstance(x,dict)]}
        except Exception as exc: report['direct_search']={'elapsed':round(time.monotonic()-t,3),'count':0,'error':f'{type(exc).__name__}: {exc}'}
        stream=getattr(module,'search_stream',None)
        if callable(stream):
            stream_rows=[]; t=time.monotonic()
            def collect(row):
                if isinstance(row,dict):
                    clean=clean_result(row,'sabina',query)
                    if clean is not None: stream_rows.append(clean)
            try:
                returned=stream(query,collect)
                if returned is not None:
                    try:
                        for row in returned:
                            if isinstance(row,dict):
                                clean=clean_result(row,'sabina',query)
                                if clean is not None: stream_rows.append(clean)
                    except TypeError: pass
                report['stream_search']={'elapsed':round(time.monotonic()-t,3),'count':len(stream_rows),'results':stream_rows}
            except Exception as exc: report['stream_search']={'elapsed':round(time.monotonic()-t,3),'count':len(stream_rows),'results':stream_rows,'error':f'{type(exc).__name__}: {exc}'}
        else: report['stream_search']={'elapsed':0.0,'count':0,'error':'search_stream_missing'}
    except Exception as exc: report['ok']=False; report['error']=f'{type(exc).__name__}: {exc}'
    report['elapsed']=round(time.monotonic()-started,3); return report
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

# Deloox stream diagnostic router is OPTIONAL.
try:
    from debug_deloox_stream_probe import router as deloox_stream_probe_router
    app.include_router(deloox_stream_probe_router)
    print('DELOOX STREAM DEBUG ROUTER: LOADED', flush=True)
except Exception as exc:
    print(
        'DELOOX STREAM DEBUG ROUTER: UNAVAILABLE '
        f'{type(exc).__name__}: {exc}',
        flush=True,
    )


# Deloox stream diagnostic v2 router is OPTIONAL.
try:
    from debug_deloox_stream_probe_v2 import router as deloox_stream_probe_v2_router
    app.include_router(deloox_stream_probe_v2_router)
    print("DELOOX STREAM DEBUG V2 ROUTER: LOADED", flush=True)
except Exception as exc:
    print(
        "DELOOX STREAM DEBUG V2 ROUTER: UNAVAILABLE "
        f"{type(exc).__name__}: {exc}",
        flush=True,
    )

# TEST 9: exact /test-store pipeline probe.

# TEST 9: exact /test-store pipeline probe.
@app.get('/api/debug/deloox-test-store-pipeline')
def deloox_test_store_pipeline(q: str = 'Born in Roma'):
    out = {
        'ok': True,
        'test': 'TEST_9_DELOOX_EXACT_TEST_STORE_PIPELINE',
        'query': q,
    }
    try:
        module = load_scraper('deloox')
        search = getattr(module, 'search', None)
        if not callable(search):
            raise RuntimeError('deloox scraper search(query) is not callable')

        raw = search(q)
        raw_rows = [] if raw is None else list(raw) if not isinstance(raw, list) else raw

        cleaned_rows = []
        dropped = []
        for idx, item in enumerate(raw_rows):
            if not isinstance(item, dict):
                dropped.append({
                    'index': idx,
                    'reason': 'not_dict',
                    'type': type(item).__name__,
                })
                continue
            try:
                cleaned = clean_result(item, 'deloox', q)
                if cleaned is None:
                    dropped.append({
                        'index': idx,
                        'reason': 'clean_result_returned_none',
                        'url': item.get('url'),
                        'name': item.get('name'),
                        'brand': item.get('brand'),
                    })
                else:
                    cleaned_rows.append(cleaned)
            except Exception as exc:
                dropped.append({
                    'index': idx,
                    'reason': 'clean_result_exception',
                    'type': type(exc).__name__,
                    'error': str(exc),
                    'url': item.get('url'),
                    'name': item.get('name'),
                    'brand': item.get('brand'),
                })

        def urls(rows):
            return [
                r.get('url')
                for r in rows
                if isinstance(r, dict) and r.get('url')
            ]

        raw_urls = urls(raw_rows)
        clean_urls = urls(cleaned_rows)

        # Reproduce run_store() exactly, but expose intermediate stages.
        report = run_store('deloox', q)

        out['runtime'] = {
            'scraper_file': getattr(module, '__file__', ''),
            'search_callable': callable(search),
        }
        out['direct_search'] = {
            'raw_count': len(raw_rows),
            'cleaned_count': len(cleaned_rows),
            'raw_urls': raw_urls,
            'cleaned_urls': clean_urls,
            'dropped_count': len(dropped),
            'dropped': dropped,
        }
        out['test_store_equivalent'] = {
            'status': report.get('status'),
            'count': report.get('count'),
            'urls': urls(report.get('results') or []),
            'error': report.get('error'),
        }

        for label, rowset in (
            ('raw', raw_rows),
            ('cleaned', cleaned_rows),
            ('test_store', report.get('results') or []),
        ):
            u = urls(rowset)
            out[label + '_ivory'] = {
                'donna_1400164': any('1400164' in x for x in u),
                'uomo_1400167': any('1400167' in x for x in u),
            }

        return out
    except Exception as exc:
        out['ok'] = False
        out['error_type'] = type(exc).__name__
        out['error'] = str(exc)
        return out

# TEST 10: one Deloox search, then local clean_result only.
@app.get('/api/debug/deloox-clean-only')
def deloox_clean_only(q: str = 'Born in Roma'):
    out = {
        'ok': True,
        'test': 'TEST_10_DELOOX_SEARCH_ONCE_CLEAN_RESULT_ONLY',
        'query': q,
    }
    try:
        module = load_scraper('deloox')
        search = getattr(module, 'search', None)
        if not callable(search):
            raise RuntimeError('Deloox search(query) is not callable')

        # Exactly ONE network-backed Deloox search.
        raw = search(q)
        raw = [] if raw is None else raw
        if not isinstance(raw, list):
            raw = list(raw)

        raw_urls = [
            r.get('url') for r in raw
            if isinstance(r, dict) and r.get('url')
        ]

        cleaned = []
        dropped = []

        # Everything after this point is local processing only.
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                dropped.append({
                    'index': i,
                    'reason': 'not_dict',
                    'type': type(item).__name__,
                })
                continue

            try:
                result = clean_result(item, 'deloox', q)
            except Exception as exc:
                dropped.append({
                    'index': i,
                    'reason': 'clean_result_exception',
                    'error_type': type(exc).__name__,
                    'error': str(exc),
                    'url': item.get('url'),
                    'name': item.get('name'),
                    'brand': item.get('brand'),
                })
                continue

            if result is None:
                dropped.append({
                    'index': i,
                    'reason': 'clean_result_none',
                    'url': item.get('url'),
                    'name': item.get('name'),
                    'brand': item.get('brand'),
                    'price': item.get('price'),
                })
            else:
                cleaned.append(result)

        cleaned_urls = [
            r.get('url') for r in cleaned
            if isinstance(r, dict) and r.get('url')
        ]

        out['runtime'] = {
            'main_file': __file__,
            'scraper_file': getattr(module, '__file__', ''),
            'search_callable': True,
        }
        out['search'] = {
            'raw_count': len(raw),
            'raw_urls': raw_urls,
            'ivory_donna': any('1400164' in u for u in raw_urls),
            'ivory_uomo': any('1400167' in u for u in raw_urls),
        }
        out['clean_result'] = {
            'cleaned_count': len(cleaned),
            'cleaned_urls': cleaned_urls,
            'dropped_count': len(dropped),
            'dropped': dropped,
            'ivory_donna': any('1400164' in u for u in cleaned_urls),
            'ivory_uomo': any('1400167' in u for u in cleaned_urls),
        }
        out['comparison'] = {
            'raw_to_clean_loss': len(raw) - len(cleaned),
            'urls_lost_by_clean_result': sorted(set(raw_urls) - set(cleaned_urls)),
        }
        return out

    except Exception as exc:
        out['ok'] = False
        out['error_type'] = type(exc).__name__
        out['error'] = str(exc)
        return out

# TEST 11: isolate ProductMatcher on the two known Ivory rows.
@app.get('/api/debug/deloox-ivory-matcher')
def deloox_ivory_matcher():
    out = {
        'ok': True,
        'test': 'TEST_11_DELOOX_IVORY_PRODUCT_MATCHER_ISOLATION',
        'query': 'Born in Roma',
    }
    try:
        # Locate the same matcher objects/functions used by clean_result,
        # without performing another Deloox search.
        import inspect
        import importlib

        mainmod = importlib.import_module('main')
        scraper = importlib.import_module('scrapers.deloox.scraper')

        candidates = {}
        for name in dir(mainmod):
            obj = getattr(mainmod, name, None)
            lname = name.lower()
            if 'matcher' in lname or 'family' in lname:
                candidates[name] = {
                    'type': type(obj).__name__,
                    'callable': callable(obj),
                }

        # Find matcher-like globals, including imported matcher modules.
        matcher_obj = None
        matcher_name = None
        for name in dir(mainmod):
            obj = getattr(mainmod, name, None)
            if 'matcher' in name.lower() and obj is not None:
                if hasattr(obj, 'match') and callable(getattr(obj, 'match')):
                    matcher_obj = obj
                    matcher_name = name
                    break

        out['runtime'] = {
            'main_file': getattr(mainmod, '__file__', ''),
            'scraper_file': getattr(scraper, '__file__', ''),
            'matcher_name': matcher_name,
            'matcher_type': type(matcher_obj).__name__ if matcher_obj is not None else None,
            'matcher_callable': bool(matcher_obj is not None),
            'main_matcher_candidates': candidates,
        }

        rows = [
            {
                'url': 'https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html',
                'brand': 'Valentino',
                'name': 'Valentino Born in Roma Ivory Uomo Eau de Toilette Limited edition 100 ml',
                'price': '100,49 €',
                'price_num': 100.49,
            },
            {
                'url': 'https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html',
                'brand': 'Valentino',
                'name': 'Valentino Donna Born in Roma Ivory Eau de Parfum Limited edition 100 ml',
                'price': '121,59 €',
                'price_num': 121.59,
            },
        ]

        # Inspect clean_result source so the diagnostic can report the exact
        # identity function path without guessing.
        clean_src = inspect.getsource(clean_result)
        out['clean_result_source_excerpt'] = clean_src[:8000]

        results = []
        if matcher_obj is not None:
            for row in rows:
                try:
                    # Try the common matcher API with keyword args first.
                    try:
                        r = matcher_obj.match(
                            query='Born in Roma',
                            brand=row['brand'],
                            name=row['name'],
                            price=row['price'],
                            url=row['url'],
                        )
                    except TypeError:
                        try:
                            r = matcher_obj.match(
                                row['name'],
                                brand=row['brand'],
                                query='Born in Roma',
                            )
                        except TypeError:
                            r = matcher_obj.match(row['name'])

                    results.append({
                        'url': row['url'],
                        'name': row['name'],
                        'returned_type': type(r).__name__,
                        'returned': r,
                    })
                except Exception as exc:
                    results.append({
                        'url': row['url'],
                        'name': row['name'],
                        'error_type': type(exc).__name__,
                        'error': str(exc),
                    })

        out['matcher_direct'] = results
        return out
    except Exception as exc:
        out['ok'] = False
        out['error_type'] = type(exc).__name__
        out['error'] = str(exc)
        return out

# TEST 12: exact ProductMatcher signature + exact _apply_product_identity call.
@app.get('/api/debug/deloox-ivory-matcher-exact')
def deloox_ivory_matcher_exact():
    out = {
        'ok': True,
        'test': 'TEST_12_EXACT_PRODUCT_MATCHER_AND_IDENTITY_CALL',
    }
    try:
        import inspect
        import importlib

        mainmod = importlib.import_module('main')
        matcher = getattr(mainmod, 'PRODUCT_MATCHER', None)
        apply_identity = getattr(mainmod, '_apply_product_identity', None)

        out['runtime'] = {
            'main_file': getattr(mainmod, '__file__', ''),
            'matcher_type': type(matcher).__name__ if matcher is not None else None,
            'matcher_signature': str(inspect.signature(matcher.match)) if matcher is not None else None,
            'apply_identity_signature': str(inspect.signature(apply_identity)) if callable(apply_identity) else None,
            'apply_identity_source': inspect.getsource(apply_identity)[:12000] if callable(apply_identity) else None,
        }

        rows = [
            {
                'url': 'https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html',
                'brand': 'Valentino',
                'name': 'Valentino Born in Roma Ivory Uomo Eau de Toilette Limited edition 100 ml',
                'price': '100,49 €',
                'price_num': 100.49,
            },
            {
                'url': 'https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html',
                'brand': 'Valentino',
                'name': 'Valentino Donna Born in Roma Ivory Eau de Parfum Limited edition 100 ml',
                'price': '121,59 €',
                'price_num': 121.59,
            },
        ]

        direct = []
        for row in rows:
            item = dict(row)
            try:
                # Discover the exact parameter names and call match with
                # the actual API, rather than guessing its signature.
                sig = inspect.signature(matcher.match)
                kwargs = {}
                positional = []
                for p in sig.parameters.values():
                    if p.name == 'self':
                        continue
                    if p.name == 'query':
                        kwargs[p.name] = 'Born in Roma'
                    elif p.name in ('brand',):
                        kwargs[p.name] = row['brand']
                    elif p.name in ('name', 'product_name', 'title'):
                        kwargs[p.name] = row['name']
                    elif p.name in ('url', 'product_url'):
                        kwargs[p.name] = row['url']
                    elif p.name in ('item', 'product', 'row'):
                        kwargs[p.name] = row
                    elif p.default is inspect._empty:
                        # If an unknown required parameter exists, expose it
                        # rather than inventing a value.
                        raise RuntimeError(
                            f"Unknown required match parameter: {p.name}"
                        )
                result = matcher.match(*positional, **kwargs)
                direct.append({
                    'url': row['url'],
                    'returned_type': type(result).__name__,
                    'returned': result,
                })
            except Exception as exc:
                direct.append({
                    'url': row['url'],
                    'error_type': type(exc).__name__,
                    'error': str(exc),
                })

        out['matcher_exact'] = direct

        identity = []
        if callable(apply_identity):
            for row in rows:
                try:
                    result = apply_identity(dict(row), 'Born in Roma')
                    identity.append({
                        'url': row['url'],
                        'returned_type': type(result).__name__,
                        'returned': result,
                    })
                except Exception as exc:
                    identity.append({
                        'url': row['url'],
                        'error_type': type(exc).__name__,
                        'error': str(exc),
                    })
        out['apply_product_identity_exact'] = identity

        return out
    except Exception as exc:
        out['ok'] = False
        out['error_type'] = type(exc).__name__
        out['error'] = str(exc)
        return out


# TEST 13: exact Deloox target trace — Purple Melancholia Donna 1391716.
# Diagnostic only. Does NOT modify scraper/ProductMatcher/family_registry.
@app.get('/api/debug/deloox-purple-1391716')
def deloox_purple_1391716(q: str = 'Born in Roma'):
    TARGET_ID = '1391716'
    out = {
        'ok': True,
        'test': 'TEST_13_DELOOX_TARGET_1391716_TRACE',
        'query': q,
        'target_id': TARGET_ID,
        'target_name': 'Valentino Born in Roma Purple Melancholia Donna',
    }

    try:
        module = load_scraper('deloox')
        search = getattr(module, 'search', None)
        discover = getattr(module, 'discover', None)
        parse_product = getattr(module, 'parse_product', None)
        row_from_card = getattr(module, '_row_from_card', None)

        out['runtime'] = {
            'scraper_file': getattr(module, '__file__', ''),
            'search_callable': callable(search),
            'discover_callable': callable(discover),
            'parse_product_callable': callable(parse_product),
            'row_from_card_callable': callable(row_from_card),
        }

        if not callable(discover):
            raise RuntimeError('Deloox discover(query) is not callable')

        requests_module = getattr(module, 'requests', None)
        if (
            requests_module is not None
            and hasattr(requests_module, 'Session')
        ):
            session = requests_module.Session()
        else:
            import requests
            session = requests.Session()

        # STEP 1 — exact target in discover()
        t = time.monotonic()
        candidates = discover(session, q) or []

        target_candidates = [
            item for item in candidates
            if isinstance(item, (tuple, list))
            and len(item) >= 1
            and TARGET_ID in str(item[0])
        ]

        out['discover'] = {
            'elapsed': round(time.monotonic() - t, 3),
            'candidate_count': len(candidates),
            'target_found': bool(target_candidates),
            'target_candidates': [
                {
                    'url': item[0],
                    'info_type': (
                        type(item[1]).__name__
                        if len(item) > 1 else None
                    ),
                    'info_repr': (
                        repr(item[1])[:4000]
                        if len(item) > 1 else None
                    ),
                }
                for item in target_candidates
            ],
        }

        # STEP 2 — exact _row_from_card() path
        if target_candidates and callable(row_from_card):
            url = target_candidates[0][0]
            info = target_candidates[0][1]
            context = ''
            image = ''

            if isinstance(info, (tuple, list)):
                if len(info) >= 2:
                    context = info[1]
                if len(info) >= 3:
                    image = info[2]

            try:
                t = time.monotonic()
                try:
                    card_row = row_from_card(
                        url, context, q, image
                    )
                except TypeError:
                    card_row = row_from_card(
                        url, context, q
                    )

                out['row_from_card'] = {
                    'elapsed': round(time.monotonic() - t, 3),
                    'accepted': isinstance(card_row, dict),
                    'row': card_row,
                    'context_preview': str(context)[:3000],
                }
            except Exception as exc:
                out['row_from_card'] = {
                    'accepted': False,
                    'exception_type': type(exc).__name__,
                    'error': str(exc),
                }
        else:
            out['row_from_card'] = {
                'skipped': True,
                'reason': (
                    'target_not_in_discover'
                    if not target_candidates
                    else 'row_from_card_unavailable'
                ),
            }

        # STEP 3 — exact parse_product() path
        if target_candidates and callable(parse_product):
            url = target_candidates[0][0]

            try:
                t = time.monotonic()
                parsed = parse_product(url, q)

                out['parse_product'] = {
                    'elapsed': round(time.monotonic() - t, 3),
                    'count': len(parsed or []),
                    'rows': parsed or [],
                    'accepted': bool(parsed),
                }
            except Exception as exc:
                out['parse_product'] = {
                    'accepted': False,
                    'exception_type': type(exc).__name__,
                    'error': str(exc),
                }
        else:
            out['parse_product'] = {
                'skipped': True,
                'reason': (
                    'target_not_in_discover'
                    if not target_candidates
                    else 'parse_product_unavailable'
                ),
            }

        # STEP 4 — real production search()
        if not callable(search):
            raise RuntimeError(
                'Deloox search(query) is not callable'
            )

        t = time.monotonic()
        final_rows = search(q)
        final_rows = [] if final_rows is None else list(final_rows)

        target_final_rows = [
            row for row in final_rows
            if isinstance(row, dict)
            and TARGET_ID in str(row.get('url') or '')
        ]

        out['search'] = {
            'elapsed': round(time.monotonic() - t, 3),
            'count': len(final_rows),
            'target_present': bool(target_final_rows),
            'target_rows': target_final_rows,
        }

        discovered = bool(target_candidates)
        card_accepted = bool(
            out.get('row_from_card', {}).get('accepted')
        )
        parsed = bool(
            out.get('parse_product', {}).get('accepted')
        )
        final_present = bool(
            out.get('search', {}).get('target_present')
        )

        if final_present:
            result = 'TARGET_REACHES_FINAL_SEARCH'
        elif not discovered:
            result = 'LOST_IN_DISCOVER'
        elif not card_accepted and not parsed:
            result = (
                'DISCOVER_HAS_TARGET_BUT_'
                'CARD_AND_PRODUCT_PARSER_DROP_IT'
            )
        else:
            result = (
                'PARSER_HAS_TARGET_BUT_'
                'SEARCH_DROPS_IT'
            )

        out['diagnosis'] = {
            'discovered': discovered,
            'card_accepted': card_accepted,
            'product_page_parsed': parsed,
            'final_search_present': final_present,
            'result': result,
        }

        return out

    except Exception as exc:
        out['ok'] = False
        out['error_type'] = type(exc).__name__
        out['error'] = str(exc)
        return out


# TEST 14: Deloox Born in Roma candidate/result audit.
# Diagnostic only. Does NOT modify scraper/ProductMatcher/family_registry.
@app.get('/api/debug/deloox-born-audit')
def deloox_born_audit(q: str = 'Born in Roma'):
    out = {
        'ok': True,
        'test': 'TEST_14_DELOOX_BORN_IN_ROMA_CANDIDATE_RESULT_AUDIT',
        'query': q,
    }

    try:
        module = load_scraper('deloox')
        discover = getattr(module, 'discover', None)
        search = getattr(module, 'search', None)
        parse_product = getattr(module, 'parse_product', None)
        row_from_card = getattr(module, '_row_from_card', None)

        if not callable(discover):
            raise RuntimeError('Deloox discover() unavailable')
        if not callable(search):
            raise RuntimeError('Deloox search() unavailable')

        import requests
        session = requests.Session()

        # DISCOVERY
        t = time.monotonic()
        candidates = discover(session, q) or []
        discover_elapsed = round(time.monotonic() - t, 3)

        def candidate_url(item):
            try:
                return str(item[0])
            except Exception:
                return ''

        target_ids = [
            '1214438','1214441','1254088',
            '1294084','1391716','1392142','1393411',
            '1359237','1359240','1400164','1400167'
        ]

        candidate_audit = []

        for idx, item in enumerate(candidates):
            url = candidate_url(item)
            info = item[1] if len(item) > 1 else None

            context = ''
            image = ''

            if isinstance(info, (tuple, list)):
                if len(info) >= 2:
                    context = info[1]
                if len(info) >= 3:
                    image = info[2]

            entry = {
                'index': idx,
                'url': url,
                'product_id': next(
                    (pid for pid in target_ids if pid in url),
                    None
                ),
                'info_repr': repr(info)[:1500],
                'context_preview': str(context)[:1200],
            }

            if callable(row_from_card):
                try:
                    try:
                        card = row_from_card(
                            url, context, q, image
                        )
                    except TypeError:
                        card = row_from_card(
                            url, context, q
                        )

                    entry['card'] = {
                        'accepted': isinstance(card, dict),
                        'row': card,
                    }
                except Exception as exc:
                    entry['card'] = {
                        'accepted': False,
                        'exception': f'{type(exc).__name__}: {exc}',
                    }

            if callable(parse_product):
                try:
                    # Only parse candidates that the card rejected.
                    if not entry.get('card', {}).get('accepted'):
                        t2 = time.monotonic()
                        parsed = parse_product(url, q)
                        entry['product_page'] = {
                            'elapsed': round(
                                time.monotonic() - t2, 3
                            ),
                            'count': len(parsed or []),
                            'rows': parsed or [],
                        }
                except Exception as exc:
                    entry['product_page'] = {
                        'exception': f'{type(exc).__name__}: {exc}',
                    }

            candidate_audit.append(entry)

        # ONE REAL SEARCH
        t = time.monotonic()
        rows = search(q) or []
        rows = list(rows)
        search_elapsed = round(time.monotonic() - t, 3)

        result_audit = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue

            url = str(row.get('url') or '')
            name = str(row.get('name') or '')
            result_audit.append({
                'index': idx,
                'url': url,
                'name': name,
                'price_num': row.get('price_num'),
                'available': row.get('available'),
                'size_ml': row.get('size_ml'),
                'product_id': next(
                    (pid for pid in target_ids if pid in url),
                    None
                ),
            })

        candidate_urls = {
            e['url'] for e in candidate_audit if e['url']
        }
        result_urls = {
            e['url'] for e in result_audit if e['url']
        }

        # Extract Born-related candidate/result names using URL identity,
        # not neighbouring card text.
        born_candidates = [
            e for e in candidate_audit
            if 'born-in-roma' in e['url'].lower()
        ]
        born_results = [
            e for e in result_audit
            if 'born-in-roma' in e['url'].lower()
        ]

        out['runtime'] = {
            'scraper_file': getattr(module, '__file__', ''),
            'BORN_IN_ROMA_MAX_CANDIDATES': getattr(
                module, 'BORN_IN_ROMA_MAX_CANDIDATES', None
            ),
            'MAX_CANDIDATES': getattr(
                module, 'MAX_CANDIDATES', None
            ),
            'MAX_RESULTS': getattr(
                module, 'MAX_RESULTS', None
            ),
        }

        out['discover'] = {
            'elapsed': discover_elapsed,
            'candidate_count': len(candidates),
            'born_candidate_count': len(born_candidates),
            'born_candidates': born_candidates,
        }

        out['search'] = {
            'elapsed': search_elapsed,
            'result_count': len(rows),
            'born_result_count': len(born_results),
            'born_results': born_results,
        }

        out['comparison'] = {
            'born_candidates_not_in_final_search': sorted(
                {
                    e['url'] for e in born_candidates
                    if e['url'] not in result_urls
                }
            ),
            'final_results_not_in_discover': sorted(
                {
                    e['url'] for e in born_results
                    if e['url'] not in candidate_urls
                }
            ),
        }

        out['summary'] = {
            'discover_count': len(candidates),
            'search_count': len(rows),
            'born_candidates': len(born_candidates),
            'born_final_results': len(born_results),
            'candidate_urls_lost_before_final': len(
                {
                    e['url'] for e in born_candidates
                    if e['url'] not in result_urls
                }
            ),
        }

        return out

    except Exception as exc:
        out['ok'] = False
        out['error_type'] = type(exc).__name__
        out['error'] = str(exc)
        return out

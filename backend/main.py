from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib, json, os, signal, subprocess, sys, threading, time, traceback, uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_VERSION = '2.5-progressive-fast-first'
app = FastAPI(title='ScentHunter API', version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

STORES = ['bplatz','deloox','parfumcity','parfumzentrum','perfumemarket','sabina','orioudh','notino']
STORE_LABELS = {'bplatz':'Bplatz','deloox':'Deloox','parfumcity':'ParfumCity','parfumzentrum':'ParfumZentrum','perfumemarket':'PerfumeMarket','sabina':'Sabina','orioudh':'Orioudh','notino':'Notino'}
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / 'frontend' / 'index.html'

LIGHTWEIGHT_STORES = ['bplatz','parfumcity','parfumzentrum','perfumemarket','orioudh']
NETWORK_HEAVY_STORES = ['deloox']
BROWSER_STORES = ['sabina','notino']
try:
    LIGHT_WORKERS = max(1, min(len(LIGHTWEIGHT_STORES), int(os.getenv('SCENTHUNTER_LIGHT_WORKERS', '2'))))
except ValueError:
    LIGHT_WORKERS = len(LIGHTWEIGHT_STORES)
NETWORK_WORKERS = 1
BROWSER_WORKERS = 1
STORE_TIMEOUT_SECONDS = 60.0
STORE_TIMEOUTS = {'bplatz':60.0,'deloox':75.0,'parfumcity':60.0,'parfumzentrum':60.0,'perfumemarket':60.0,'sabina':70.0,'orioudh':60.0,'notino':45.0}
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


def clean_result(item, store):
    result = dict(item)
    machine_store = _normalise_store(result.get('store') or result.get('shop'), store)
    result['store'] = machine_store
    result.setdefault('shop', STORE_LABELS.get(machine_store, machine_store))
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
    return result


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
        cleaned=[clean_result(x,store) for x in rows if isinstance(x,dict)]
        return {'store':store,'status':'ok' if cleaned else 'empty','elapsed':round(time.monotonic()-started,3),'count':len(cleaned),'results':cleaned,'error':None}
    except Exception as exc:
        traceback.print_exc()
        return {'store':store,'status':'error','elapsed':round(time.monotonic()-started,3),'count':0,'results':[],'error':f'{type(exc).__name__}: {exc}'}


WORKER_CODE = r'''
import importlib, json, sys
store=sys.argv[1]; query=sys.argv[2]
try:
    module=importlib.import_module(f'scrapers.{store}.scraper')
    search=getattr(module,'search',None)
    if not callable(search): raise RuntimeError(f'scraper {store} non espone search(query)')
    raw=search(query)
    if raw is None: rows=[]
    elif isinstance(raw,list): rows=raw
    elif isinstance(raw,tuple): rows=list(raw)
    else:
        try: rows=list(raw)
        except TypeError: rows=[]
    print(json.dumps({'ok':True,'rows':rows},ensure_ascii=False,default=str),flush=True)
except BaseException as exc:
    print(json.dumps({'ok':False,'error':f'{type(exc).__name__}: {exc}'},ensure_ascii=False),flush=True)
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


def _run_store_subprocess(store, query):
    started=time.monotonic(); timeout=STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS)
    env=os.environ.copy(); current=env.get('PYTHONPATH',''); env['PYTHONPATH']=str(BASE_DIR)+(os.pathsep+current if current else '')
    process=None
    try:
        process=subprocess.Popen([sys.executable,'-c',WORKER_CODE,store,query],cwd=str(BASE_DIR),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',start_new_session=(os.name!='nt'))
        stdout,stderr=process.communicate(timeout=timeout)
        payload=None
        for line in reversed((stdout or '').splitlines()):
            try: candidate=json.loads(line.strip())
            except json.JSONDecodeError: continue
            if isinstance(candidate,dict) and ('ok' in candidate or 'rows' in candidate): payload=candidate; break
        elapsed=round(time.monotonic()-started,3)
        if process.returncode!=0:
            error=f'worker_exit_{process.returncode}'
            if isinstance(payload,dict) and payload.get('error'): error += ': '+str(payload['error'])
            elif stderr and stderr.strip(): error += ': '+stderr.strip()[-1000:]
            return _empty_report(store,elapsed=elapsed,error=error)
        if not isinstance(payload,dict) or payload.get('ok') is not True: return _empty_report(store,elapsed=elapsed,error='worker_invalid_response')
        rows=payload.get('rows') if isinstance(payload.get('rows'),list) else []
        cleaned=[clean_result(x,store) for x in rows if isinstance(x,dict)]
        return {'store':store,'status':'ok' if cleaned else 'empty','elapsed':elapsed,'count':len(cleaned),'results':cleaned,'error':None}
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


def _run_controlled_store(store,query,on_report):
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
    try: report=_run_store_subprocess(store,query)
    finally:
        if semaphore is not None: semaphore.release()
    if report.get('status')=='error':
        if str(report.get('error','')).startswith('store_timeout_'): print(f"STORE TIMEOUT store={store} timeout={report['error']}",flush=True)
        else: print(f"STORE ERROR store={store} error={report.get('error')}",flush=True)
    print(f"STORE END store={store} status={report.get('status')} elapsed={report.get('elapsed')} count={report.get('count')}",flush=True)
    on_report(report)


FAST_FIRST_STORES = ['bplatz', 'parfumcity']
SECONDARY_LIGHT_STORES = ['orioudh', 'perfumemarket', 'parfumzentrum']
DEFERRED_STORES = ['deloox', 'sabina', 'notino']


def collect_store_reports_isolated(query,stores,on_report=None):
    """Progressive resource-aware scheduler.

    The first two proven-fast stores get the machine to themselves initially.
    As soon as the first result/empty/error arrives, the remaining stores are
    released. This avoids the Render Free CPU/RAM contention that previously
    turned 5-8 second scrapers into 20-45 second scrapers when all 8 started
    together. Every store remains independently killable and publishes as soon
    as it finishes.
    """
    requested=list(stores)
    reports={}; lock=threading.Lock(); threads=[]
    first_release=threading.Event()
    started_stores=set()
    started_lock=threading.Lock()

    def publish(report):
        with lock: reports[report['store']]=report
        first_release.set()
        if callable(on_report): on_report(report)

    def start_store(store):
        with started_lock:
            if store in started_stores or store not in requested: return None
            started_stores.add(store)
        t=threading.Thread(target=_run_controlled_store,args=(store,query,publish),daemon=True,name=f'scenthunter-store-{store}')
        t.start(); threads.append(t)
        return t

    # Phase 1: only the two stores that have historically produced the fastest
    # real offers. Do not let Deloox/Chromium consume the initial CPU/RAM burst.
    initial=[s for s in FAST_FIRST_STORES if s in requested]
    if not initial:
        initial=[s for s in requested[:2]]
    for store in initial: start_store(store)

    # Release the rest as soon as one of the fast stores has reported. The
    # fallback timer guarantees a broken fast store cannot delay the others.
    release_deadline=time.monotonic()+8.0
    while not first_release.is_set() and time.monotonic()<release_deadline:
        first_release.wait(timeout=0.2)

    remaining=[s for s in requested if s not in started_stores]
    for store in remaining: start_store(store)

    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in list(threads):
        t.join(timeout=max(0.0,deadline-time.monotonic()))
    unfinished=[t.name.rsplit('scenthunter-store-',1)[-1] for t in threads if t.is_alive()]
    if unfinished:
        print(f'SEARCH SUPERVISORS STILL RUNNING stores={unfinished}',flush=True)
        with lock:
            for store in unfinished:
                reports.setdefault(store,_empty_report(store,elapsed=JOB_TIMEOUT_SECONDS,error='job_timeout'))
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


def _publish_store(job_id,report):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'): return
        store=report['store']; job['stores'][store]={'status':report['status'],'elapsed':report['elapsed'],'count':report['count']}
        if report.get('error'): job['errors'][store]=report['error']
        if report.get('results'): job['results'].extend(report['results'])
        job['results']=sort_results(dedupe_results(job['results'])); total=len(job['results'])
    print(f"SEARCH PUBLISH job={job_id} store={store} count={report.get('count')} total={total}",flush=True)


def _run_job(job_id,query):
    started=time.monotonic(); print(f'SEARCH START job={job_id} query={query!r}',flush=True)
    collect_store_reports_isolated(query,STORES,on_report=lambda r:_publish_store(job_id,r))
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

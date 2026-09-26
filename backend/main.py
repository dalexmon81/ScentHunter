from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
import json, threading, time, re, unicodedata

try:
    from product_matcher import ProductMatcher
except Exception as exc:
    ProductMatcher = None
    print(f'ProductMatcher unavailable: {type(exc).__name__}: {exc}', flush=True)

from catalog_engine_v5 import STORES, STORE_LABELS, db, search_local, refresh_candidates, store_status, sync_all

APP_VERSION = '5.0-catalog-first'
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / 'frontend' / 'index.html'
PRODUCT_CATALOG_PATH = BASE_DIR / 'product_catalog.json'
FAMILY_REGISTRY_PATH = BASE_DIR / 'family_registry.json'
CATALOG_SYNC_INTERVAL = 1800
CACHE_MAX_AGE = 1800
SEARCH_REFRESH_BUDGET = 11.0

app = FastAPI(title='ScentHunter API', version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

JOBS = {}
JOBS_LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()


def load_matcher():
    if ProductMatcher is None:
        return None
    try:
        with open(PRODUCT_CATALOG_PATH, encoding='utf-8') as f:
            catalog = json.load(f)
        family = None
        if FAMILY_REGISTRY_PATH.exists():
            with open(FAMILY_REGISTRY_PATH, encoding='utf-8') as f:
                family = json.load(f)
        return ProductMatcher(catalog=catalog, family_registry=family)
    except Exception as exc:
        print(f'MATCHER_INIT_ERROR {type(exc).__name__}: {exc}', flush=True)
        return None

MATCHER = load_matcher()


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', s)).strip()


def resolve_offer(item, query):
    if not isinstance(item, dict):
        return None
    if MATCHER is None:
        return None
    offer = dict(item)
    # The store name is provenance, never product brand.
    brand = str(offer.get('brand') or '').strip()
    store = str(offer.get('store') or '').strip()
    if brand and norm(brand) == norm(store):
        offer['brand'] = ''
    try:
        match = MATCHER.match(offer, query)
    except Exception as exc:
        offer['_match_error'] = f'{type(exc).__name__}: {exc}'
        return None
    if not isinstance(match, dict) or not match.get('catalog_id'):
        return None
    out = dict(offer)
    out.update(match)
    out['_match_status'] = 'matched'
    out['match_confidence'] = out.get('confidence')
    return out


def aggregate(rows, query):
    groups = {}
    unresolved = []
    for row in rows:
        matched = resolve_offer(row, query)
        if not matched:
            continue
        cid = str(matched.get('catalog_id') or '')
        if not cid:
            continue
        group = groups.setdefault(cid, {
            'catalog_id': cid,
            'canonical_name': matched.get('canonical_name'),
            'canonical_brand': matched.get('canonical_brand'),
            'canonical_image': matched.get('canonical_image'),
            'offers': [],
        })
        offer = {
            'store': matched.get('store'),
            'shop': matched.get('store'),
            'name': matched.get('name'),
            'brand': matched.get('brand'),
            'price': matched.get('price'),
            'price_num': matched.get('price_num'),
            'currency': matched.get('currency') or 'EUR',
            'availability': matched.get('availability') or 'unknown',
            'available': matched.get('available'),
            'url': matched.get('url'),
            'image': matched.get('image') or matched.get('canonical_image'),
            'size_ml': matched.get('size_ml'),
            'gtin': matched.get('gtin'),
            'sku': matched.get('sku'),
            'fetched_at': matched.get('fetched_at'),
            'price_stale': bool(matched.get('price_stale')),
        }
        group['offers'].append(offer)
    results = []
    for group in groups.values():
        group['offers'].sort(key=lambda x: (float(x['price_num']) if isinstance(x.get('price_num'), (int,float)) else 1e99, x.get('store') or ''))
        prices=[x['price_num'] for x in group['offers'] if isinstance(x.get('price_num'),(int,float)) and x['price_num']>0]
        group['min_price']=min(prices) if prices else None
        group['store_count']=len(group['offers'])
        # Keep the frontend-compatible top-level fields too.
        group['price']=group['min_price']
        group['store']=group['offers'][0]['store'] if group['offers'] else None
        results.append(group)
    results.sort(key=lambda x: (x['min_price'] is None, x['min_price'] if x['min_price'] is not None else 1e99, x.get('canonical_name') or ''))
    return results, unresolved


def freshen(rows):
    now=time.time()
    refresh=[]
    for row in rows:
        fetched=row.get('fetched_at')
        if row.get('_needs_refresh') or not fetched or now-float(fetched)>CACHE_MAX_AGE:
            refresh.append(row)
    if not refresh:
        return rows
    # refresh_candidates itself is bounded by per-request HTTP timeout and uses a small pool.
    fresh=refresh_candidates(refresh)
    by_url={r.get('url'):r for r in fresh if r and r.get('url')}
    for row in rows:
        if row.get('url') in by_url:
            replacement=dict(by_url[row['url']])
            row.clear(); row.update(replacement)
        elif row.get('_needs_refresh'):
            # No cached value exists. Keep it out of the offer set rather than inventing a price.
            row['_refresh_failed']=True
        else:
            row['price_stale']=True
    return rows


def do_search(query):
    started=time.monotonic()
    local=search_local(query, per_store=10)
    candidate_by_store={k:0 for k in STORES}
    for row in local:
        candidate_by_store[row.get('store_key')]=candidate_by_store.get(row.get('store_key'),0)+1
    local=freshen(local)
    rows=[r for r in local if r.get('price_num') not in (None,'') and not r.get('_refresh_failed')]
    found_by_store={k:0 for k in STORES}
    for row in rows:
        found_by_store[row.get('store_key')]=found_by_store.get(row.get('store_key'),0)+1
    grouped, unresolved=aggregate(rows, query)
    status=store_status()
    errors={}
    stores={}
    for key, st in status.items():
        if st['indexed_urls'] == 0:
            query_status='NOT_READY'
        elif candidate_by_store.get(key,0) == 0:
            query_status='NOT_FOUND'
        elif found_by_store.get(key,0) == 0:
            query_status='UNVERIFIED'
        else:
            query_status='FOUND'
        stores[key]={
            'status':query_status,
            'index_status':st['status'],
            'verified': query_status in ('FOUND','NOT_FOUND'),
            'count':found_by_store.get(key,0),
            'indexed_urls':st['indexed_urls'],
            'candidate_count':candidate_by_store.get(key,0),
            'elapsed':0,
            'details':{
                'indexed_urls':st['indexed_urls'],
                'fetched_products':st['fetched_products'],
                'age_sec':st['age_sec'],
            },
        }
        if st.get('error'):
            errors[key]=st['error']
    return {
        'query':query,
        'count':len(grouped),
        'offer_count':sum(len(x['offers']) for x in grouped),
        'results':grouped,
        'unresolved_offers':unresolved,
        'identity_scope': [],
        'comparisons':[],
        'errors':errors,
        'stores':stores,
        'completed':True,
        'status':'completed' if not errors else 'completed_with_store_issues',
        'elapsed':round(time.monotonic()-started,3),
        'architecture':APP_VERSION,
    }


def job_runner(job_id, query):
    try:
        data=do_search(query)
        with JOBS_LOCK:
            JOBS[job_id].update(data, completed=True)
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id].update({'completed':True,'status':'error','count':0,'results':[], 'errors':{'job':f'{type(exc).__name__}: {exc}'}})


def sync_loop():
    # Background only. Search does not wait for this work.
    while True:
        if SYNC_LOCK.acquire(blocking=False):
            try:
                print('CATALOG SYNC START', flush=True)
                result=sync_all()
                print(f'CATALOG SYNC END {result}', flush=True)
            except Exception as exc:
                print(f'CATALOG SYNC ERROR {type(exc).__name__}: {exc}', flush=True)
            finally:
                SYNC_LOCK.release()
        time.sleep(CATALOG_SYNC_INTERVAL)


@app.on_event('startup')
def startup():
    db().close()
    threading.Thread(target=sync_loop, daemon=True, name='scenthunter-catalog-sync').start()


@app.get('/health')
def health():
    return {'status':'healthy','architecture':APP_VERSION,'stores':list(STORES),'catalog':store_status()}

@app.get('/catalog-status')
def catalog_status():
    return {'architecture':APP_VERSION,'stores':store_status()}

@app.get('/search-start')
def search_start(q: str):
    query=str(q or '').strip()
    if not query:
        return {'job_id':'','query':'','completed':True,'status':'completed','count':0,'offer_count':0,'results':[],'errors':{},'stores':{}}
    job_id=f'{int(time.time()*1000):x}-{len(JOBS)}'
    with JOBS_LOCK:
        JOBS[job_id]={'job_id':job_id,'query':query,'completed':False,'status':'running','count':0,'offer_count':0,'results':[],'errors':{},'stores':{}}
    threading.Thread(target=job_runner,args=(job_id,query),daemon=True,name=f'scenthunter-search-{job_id[:8]}').start()
    with JOBS_LOCK:
        return dict(JOBS[job_id])

@app.get('/search-status')
def search_status(job_id:str):
    with JOBS_LOCK:
        return dict(JOBS.get(job_id, {'job_id':job_id,'completed':True,'status':'error','errors':{'job':'unknown_job'},'results':[],'count':0,'offer_count':0,'stores':{}}))

@app.get('/search-status/{job_id}')
def search_status_path(job_id:str):
    return search_status(job_id)

@app.get('/search')
def search(q:str):
    return do_search(str(q or '').strip())

@app.get('/frontend')
def frontend():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'error':'frontend/index.html not found'}

@app.get('/', include_in_schema=False)
def root():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'app':'ScentHunter','status':'running','architecture':APP_VERSION}

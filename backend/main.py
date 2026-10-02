from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib, json, os, re, signal, subprocess, sys, threading, time, uuid
try:
    from product_matcher import ProductMatcher
except Exception as exc:
    ProductMatcher = None
    print(f'ProductMatcher unavailable: {type(exc).__name__}: {exc}', flush=True)
from pathlib import Path

# Catalog-first search support. The legacy isolated scraper pipeline below is
# retained for diagnostics/compatibility, but normal search uses the persistent
# catalog. Product-page hydration is a separate durable background queue.
try:
    from catalog_engine import (
        search_local as catalog_search_local,
        refresh_candidates as catalog_refresh_candidates,
        discover_store as catalog_discover_store,
        store_status as catalog_store_status,
        hydration_status as catalog_hydration_status,
        sync_all as catalog_sync_all,
        catalog_hydration_loop,
        db as catalog_db,
    )
    CATALOG_ENGINE_AVAILABLE = True
except Exception as exc:
    CATALOG_ENGINE_AVAILABLE = False
    catalog_search_local = None
    catalog_refresh_candidates = None
    catalog_discover_store = None
    catalog_store_status = None
    catalog_sync_all = None
    catalog_hydration_loop = None
    catalog_db = None
    catalog_hydration_status = None
    print(f'CATALOG_ENGINE_UNAVAILABLE: {type(exc).__name__}: {exc}', flush=True)

APP_VERSION = '5.7-catalog-targeted-refresh'
app = FastAPI(title='ScentHunter API', version=APP_VERSION)

# The persistent catalog lives on the Fly volume. A new volume starts empty,
# so discovery must be bootstrapped in the background when the application
# starts. Normal user searches never run discovery themselves.
_CATALOG_BOOTSTRAP_LOCK = threading.Lock()
_CATALOG_BOOTSTRAP_STARTED = False
_CATALOG_BOOTSTRAP_RUNNING = False
_CATALOG_BOOTSTRAP_DONE = False
_CATALOG_BOOTSTRAP_ERROR = None
_CATALOG_HYDRATION_STARTED = False
_CATALOG_HYDRATION_STOP = threading.Event()

# Controlled operational resync for stores whose persistent catalog needs to
# be rebuilt without touching the normal search path. This is deliberately
# limited to the two stores currently being repaired.
_CATALOG_RESYNC_LOCK = threading.Lock()
_CATALOG_RESYNC_RUNNING = False
_CATALOG_RESYNC_JOB_ID = None
_CATALOG_RESYNC_STARTED_AT = None
_CATALOG_RESYNC_FINISHED_AT = None
_CATALOG_RESYNC_RESULT = {}
_CATALOG_RESYNC_ERROR = None
_CATALOG_RESYNC_STORES = ('sabina', 'deloox')
# Isolated Deloox operational resync. This endpoint intentionally bypasses
# Sabina so Deloox can be rebuilt and measured independently.
_DELOOX_RESYNC_LOCK = threading.Lock()
_DELOOX_RESYNC_RUNNING = False
_DELOOX_RESYNC_JOB_ID = None
_DELOOX_RESYNC_STARTED_AT = None
_DELOOX_RESYNC_FINISHED_AT = None
_DELOOX_RESYNC_RESULT = {}
_DELOOX_RESYNC_ERROR = None


def _deloox_resync_worker(job_id):
    global _DELOOX_RESYNC_RUNNING, _DELOOX_RESYNC_FINISHED_AT
    global _DELOOX_RESYNC_RESULT, _DELOOX_RESYNC_ERROR

    result = {}
    error = None
    print(f'CATALOG DELOOX RESYNC START job={job_id}', flush=True)
    try:
        if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_discover_store):
            raise RuntimeError('catalog_discovery_unavailable')

        result = catalog_discover_store('deloox')
        if not isinstance(result, dict):
            result = {'status': 'finished', 'result': result}

        print(
            f'CATALOG DELOOX RESYNC END job={job_id} '
            f'status={result.get("status", "unknown")} '
            f'count={result.get("count", "?")}',
            flush=True,
        )
    except Exception as exc:
        error = f'{type(exc).__name__}:{exc}'
        result = {
            'status': 'DISCOVERY_ERROR',
            'count': 0,
            'error': error,
        }
        print(f'CATALOG DELOOX RESYNC ERROR job={job_id}: {error}', flush=True)
    finally:
        with _DELOOX_RESYNC_LOCK:
            _DELOOX_RESYNC_RESULT = result
            _DELOOX_RESYNC_ERROR = error
            _DELOOX_RESYNC_FINISHED_AT = time.time()
            _DELOOX_RESYNC_RUNNING = False


@app.get('/catalog/resync-deloox')
def catalog_resync_deloox_endpoint():
    """Start an isolated Deloox-only catalog discovery run."""
    global _DELOOX_RESYNC_RUNNING, _DELOOX_RESYNC_JOB_ID
    global _DELOOX_RESYNC_STARTED_AT, _DELOOX_RESYNC_FINISHED_AT
    global _DELOOX_RESYNC_RESULT, _DELOOX_RESYNC_ERROR

    if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_discover_store):
        return {
            'ok': False,
            'error': 'catalog_discovery_unavailable',
            'store': 'deloox',
        }

    with _DELOOX_RESYNC_LOCK:
        if _DELOOX_RESYNC_RUNNING:
            return {
                'ok': False,
                'status': 'already_running',
                'job_id': _DELOOX_RESYNC_JOB_ID,
                'store': 'deloox',
            }

        job_id = uuid.uuid4().hex[:12]
        _DELOOX_RESYNC_RUNNING = True
        _DELOOX_RESYNC_JOB_ID = job_id
        _DELOOX_RESYNC_STARTED_AT = time.time()
        _DELOOX_RESYNC_FINISHED_AT = None
        _DELOOX_RESYNC_RESULT = {}
        _DELOOX_RESYNC_ERROR = None

    threading.Thread(
        target=_deloox_resync_worker,
        args=(job_id,),
        daemon=True,
        name='scenthunter-catalog-deloox-resync',
    ).start()

    return {
        'ok': True,
        'status': 'started',
        'job_id': job_id,
        'store': 'deloox',
        'status_endpoint': f'/catalog/resync-deloox-status?job_id={job_id}',
        'note': 'Deloox-only discovery runs in background and does not run inside /search.',
    }


@app.get('/catalog/resync-deloox-status')
def catalog_resync_deloox_status_endpoint(job_id: str = ''):
    """Read-only status for the isolated Deloox discovery run."""
    with _DELOOX_RESYNC_LOCK:
        running = _DELOOX_RESYNC_RUNNING
        current_job = _DELOOX_RESYNC_JOB_ID
        started = _DELOOX_RESYNC_STARTED_AT
        finished = _DELOOX_RESYNC_FINISHED_AT
        result = dict(_DELOOX_RESYNC_RESULT)
        error = _DELOOX_RESYNC_ERROR

    if job_id and current_job and job_id != current_job:
        return {
            'ok': False,
            'status': 'job_not_current',
            'requested_job_id': job_id,
            'current_job_id': current_job,
        }

    return {
        'ok': True,
        'status': 'running' if running else ('finished' if current_job else 'idle'),
        'job_id': current_job,
        'store': 'deloox',
        'started_at': started,
        'finished_at': finished,
        'error': error,
        'result': result,
    }


def _catalog_is_ready():
    if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_store_status):
        return False
    try:
        statuses = catalog_store_status() or {}
        return any(
            int((statuses.get(store) or {}).get('indexed_urls') or 0) > 0
            for store in STORES
        )
    except Exception as exc:
        print(f'CATALOG READINESS ERROR: {type(exc).__name__}: {exc}', flush=True)
        return False

def _start_catalog_hydration():
    global _CATALOG_HYDRATION_STARTED
    with _CATALOG_BOOTSTRAP_LOCK:
        if _CATALOG_HYDRATION_STARTED:
            return
        if not callable(catalog_hydration_loop):
            print('CATALOG HYDRATION SKIP: catalog_engine has no hydrator', flush=True)
            return
        _CATALOG_HYDRATION_STARTED = True
    threading.Thread(
        target=catalog_hydration_loop,
        kwargs={
            'stop_event': _CATALOG_HYDRATION_STOP,
            'batch_size': 16,
            'workers': 8,
            'pause_seconds': 0.25,
        },
        daemon=True,
        name='scenthunter-catalog-hydration',
    ).start()


def _catalog_bootstrap_worker():
    global _CATALOG_BOOTSTRAP_RUNNING, _CATALOG_BOOTSTRAP_DONE, _CATALOG_BOOTSTRAP_ERROR
    with _CATALOG_BOOTSTRAP_LOCK:
        _CATALOG_BOOTSTRAP_RUNNING = True
    print('CATALOG BOOTSTRAP START: persistent catalog is empty; starting background discovery', flush=True)
    try:
        if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_sync_all):
            raise RuntimeError('catalog_engine_unavailable')
        result = catalog_sync_all()
        _start_catalog_hydration()
        ready = _catalog_is_ready()
        with _CATALOG_BOOTSTRAP_LOCK:
            _CATALOG_BOOTSTRAP_DONE = ready
            _CATALOG_BOOTSTRAP_ERROR = None if ready else 'catalog_bootstrap_finished_without_indexed_stores'
        print(
            f'CATALOG BOOTSTRAP END ready={ready} stores={len(result or {})}',
            flush=True,
        )
    except Exception as exc:
        with _CATALOG_BOOTSTRAP_LOCK:
            _CATALOG_BOOTSTRAP_ERROR = f'{type(exc).__name__}:{exc}'
        print(f'CATALOG BOOTSTRAP ERROR: {type(exc).__name__}: {exc}', flush=True)
    finally:
        with _CATALOG_BOOTSTRAP_LOCK:
            _CATALOG_BOOTSTRAP_RUNNING = False

def _catalog_targeted_resync_worker(job_id):
    global _CATALOG_RESYNC_RUNNING, _CATALOG_RESYNC_FINISHED_AT
    global _CATALOG_RESYNC_RESULT, _CATALOG_RESYNC_ERROR

    results = {}
    error = None
    print(
        f'CATALOG TARGETED RESYNC START job={job_id} stores={list(_CATALOG_RESYNC_STORES)}',
        flush=True,
    )
    try:
        if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_discover_store):
            raise RuntimeError('catalog_discovery_unavailable')

        # Run the two repairs serially. This avoids adding a second burst of
        # network/SQLite pressure while the normal hydration workers continue.
        for store in _CATALOG_RESYNC_STORES:
            try:
                result = catalog_discover_store(store)
                results[store] = result
                print(
                    f'CATALOG TARGETED RESYNC STORE={store} '
                    f'status={result.get("status") if isinstance(result, dict) else "unknown"} '
                    f'count={result.get("count") if isinstance(result, dict) else "?"}',
                    flush=True,
                )
            except Exception as exc:
                results[store] = {
                    'status': 'DISCOVERY_ERROR',
                    'count': 0,
                    'error': f'{type(exc).__name__}:{exc}',
                }
                print(
                    f'CATALOG TARGETED RESYNC STORE ERROR={store}: '
                    f'{type(exc).__name__}: {exc}',
                    flush=True,
                )
        _CATALOG_RESYNC_RESULT = results
    except Exception as exc:
        error = f'{type(exc).__name__}:{exc}'
        _CATALOG_RESYNC_ERROR = error
        print(f'CATALOG TARGETED RESYNC ERROR: {error}', flush=True)
    finally:
        _CATALOG_RESYNC_ERROR = error
        _CATALOG_RESYNC_FINISHED_AT = time.time()
        with _CATALOG_RESYNC_LOCK:
            _CATALOG_RESYNC_RUNNING = False
        print(f'CATALOG TARGETED RESYNC END job={job_id}', flush=True)


@app.get('/catalog/resync-sabina-deloox')
def catalog_resync_sabina_deloox_endpoint():
    """Start the controlled Sabina+Deloox catalog discovery repair."""
    global _CATALOG_RESYNC_RUNNING, _CATALOG_RESYNC_JOB_ID
    global _CATALOG_RESYNC_STARTED_AT, _CATALOG_RESYNC_FINISHED_AT
    global _CATALOG_RESYNC_RESULT, _CATALOG_RESYNC_ERROR

    if not CATALOG_ENGINE_AVAILABLE or not callable(catalog_discover_store):
        return {
            'ok': False,
            'error': 'catalog_discovery_unavailable',
            'stores': list(_CATALOG_RESYNC_STORES),
        }

    with _CATALOG_RESYNC_LOCK:
        if _CATALOG_RESYNC_RUNNING:
            return {
                'ok': False,
                'status': 'already_running',
                'job_id': _CATALOG_RESYNC_JOB_ID,
                'stores': list(_CATALOG_RESYNC_STORES),
            }

        job_id = uuid.uuid4().hex[:12]
        _CATALOG_RESYNC_RUNNING = True
        _CATALOG_RESYNC_JOB_ID = job_id
        _CATALOG_RESYNC_STARTED_AT = time.time()
        _CATALOG_RESYNC_FINISHED_AT = None
        _CATALOG_RESYNC_RESULT = {}
        _CATALOG_RESYNC_ERROR = None

    threading.Thread(
        target=_catalog_targeted_resync_worker,
        args=(job_id,),
        daemon=True,
        name='scenthunter-catalog-targeted-resync',
    ).start()

    return {
        'ok': True,
        'status': 'started',
        'job_id': job_id,
        'stores': list(_CATALOG_RESYNC_STORES),
        'status_endpoint': f'/catalog/resync-sabina-deloox-status?job_id={job_id}',
        'note': 'Discovery runs in background and does not run inside /search.',
    }


@app.get('/catalog/resync-sabina-deloox-status')
def catalog_resync_sabina_deloox_status_endpoint(job_id: str = ''):
    """Read-only status for the controlled Sabina+Deloox resync."""
    with _CATALOG_RESYNC_LOCK:
        running = _CATALOG_RESYNC_RUNNING
        current_job = _CATALOG_RESYNC_JOB_ID
        started = _CATALOG_RESYNC_STARTED_AT
        finished = _CATALOG_RESYNC_FINISHED_AT
        result = dict(_CATALOG_RESYNC_RESULT)
        error = _CATALOG_RESYNC_ERROR

    if job_id and current_job and job_id != current_job:
        return {
            'ok': False,
            'status': 'job_not_current',
            'requested_job_id': job_id,
            'current_job_id': current_job,
        }

    return {
        'ok': True,
        'status': 'running' if running else ('finished' if current_job else 'idle'),
        'job_id': current_job,
        'stores': list(_CATALOG_RESYNC_STORES),
        'started_at': started,
        'finished_at': finished,
        'error': error,
        'results': result,
    }


@app.on_event('startup')
def _start_catalog_bootstrap():
    global _CATALOG_BOOTSTRAP_STARTED
    with _CATALOG_BOOTSTRAP_LOCK:
        if _CATALOG_BOOTSTRAP_STARTED:
            return
        _CATALOG_BOOTSTRAP_STARTED = True
    if _catalog_is_ready():
        with _CATALOG_BOOTSTRAP_LOCK:
            global _CATALOG_BOOTSTRAP_DONE
            _CATALOG_BOOTSTRAP_DONE = True
        print('CATALOG BOOTSTRAP SKIP: persistent catalog already indexed', flush=True)
        _start_catalog_hydration()
        return
    threading.Thread(
        target=_catalog_bootstrap_worker,
        daemon=True,
        name='scenthunter-catalog-bootstrap',
    ).start()

# Read-only scraper diagnostics. This module does not participate in normal search.
try:
    from diagnose_two_scrapers import router as diagnose_two_scrapers_router
    app.include_router(diagnose_two_scrapers_router)
    from diagnose_deloox_scraper import router as diagnose_deloox_scraper_router
    app.include_router(diagnose_deloox_scraper_router)
    from diagnose_sabina_legacy_crawl import router as diagnose_sabina_legacy_crawl_router
    app.include_router(diagnose_sabina_legacy_crawl_router)
except Exception as exc:
    print(f"SCRAPER_DIAGNOSTIC_UNAVAILABLE: {type(exc).__name__}: {exc}", flush=True)
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
JOB_TIMEOUT_SECONDS = 30.0
CATALOG_REFRESH_BUDGET_SECONDS = 8.0
CATALOG_REFRESH_PER_STORE = 8
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
        method = getattr(PRODUCT_MATCHER, "build_identity_scope", None)
        if callable(method):
            return method(str(query or "").strip())
        method = getattr(PRODUCT_MATCHER, "build_query_scope", None)
        if callable(method):
            return method(str(query or "").strip())
        return []
    except Exception as exc:
        print(
            f'PRODUCT_IDENTITY_SCOPE_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return []

def _resolve_offer_identity(result, query):
    """Resolve one raw retailer offer through the central ProductMatcher.

    The canonical matcher contract is ``match(offer, query)``.  Older
    ``build_query_scope`` / ``match_offer`` calls were a different contract and
    caused valid retailer rows to remain unresolved even though the catalog
    contained the product.
    """
    if not isinstance(result, dict):
        return None

    output = dict(result)

    if PRODUCT_MATCHER is None:
        output.update({
            "_match_status": "unresolved",
            "catalog_id": None,
            "canonical_name": None,
        })
        return output

    try:
        match_method = getattr(PRODUCT_MATCHER, "match", None)
        if not callable(match_method):
            raise RuntimeError("ProductMatcher non espone match(offer, query)")

        # IMPORTANT: some retailer APIs put their own vendor/store name in
        # nested source metadata. ProductMatcher is allowed to fall back to
        # source.brand/source_brand, so even after the public ``brand`` field
        # is cleaned that retailer label can still become a false brand
        # constraint.
        #
        # For the matcher input only, build a clean identity payload. The
        # public/output object is left untouched. When the top-level brand is
        # the retailer label, remove the entire nested source identity and
        # keep the already-normalized product name as the authoritative name.
        matcher_offer = dict(output)
        matcher_brand = str(matcher_offer.get("brand") or "").strip()
        matcher_store_label = "".join(
            str(STORE_LABELS.get(
                _normalise_store(matcher_offer.get("store") or matcher_offer.get("shop"), ""),
                _normalise_store(matcher_offer.get("store") or matcher_offer.get("shop"), ""),
            ) or "")
            .lower()
            .replace("-", " ")
            .split()
        )
        matcher_brand_normalized = "".join(
            matcher_brand.lower().replace("-", " ").split()
        )
        if matcher_brand_normalized == matcher_store_label or (
            not matcher_brand_normalized
            and str(output.get("_raw_brand") or "").strip()
            and "".join(str(output.get("_raw_brand") or "").lower().replace("-", " ").split()) == matcher_store_label
        ):
            matcher_offer["brand"] = ""
            matcher_offer.pop("manufacturer", None)
            source = matcher_offer.get("source")
            if isinstance(source, dict):
                clean_source = dict(source)
                for key in ("source_brand", "brand", "manufacturer"):
                    clean_source.pop(key, None)
                matcher_offer["source"] = clean_source
            elif source is not None:
                matcher_offer.pop("source", None)

        match = match_method(matcher_offer, str(query or "").strip())
    except Exception as exc:
        print(
            f"PRODUCT_MATCHER_MATCH_ERROR: {type(exc).__name__}: {exc}",
            flush=True,
        )
        output.update({
            "_match_status": "unresolved",
            "catalog_id": None,
            "canonical_name": None,
            "_match_error": f"{type(exc).__name__}: {exc}",
        })
        return output

    if not isinstance(match, dict):
        # ``None`` can mean an ordinary unresolved identity or an intentional
        # non-publish rejection. Ask the same central matcher for the explicit
        # rejection reason instead of duplicating its rules in main.py.
        rejection_method = getattr(PRODUCT_MATCHER, "rejection_reason", None)
        rejection_reason = None
        if callable(rejection_method):
            try:
                rejection_reason = rejection_method(matcher_offer)
            except Exception as exc:
                print(
                    f"PRODUCT_MATCHER_REJECTION_STATUS_ERROR: {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if rejection_reason:
            output.update({
                "_match_status": "rejected",
                "_reject_reason": rejection_reason,
                "catalog_id": None,
                "canonical_name": None,
            })
            return output

        # A known family query has a closed identity scope: ProductMatcher is
        # authoritative for the registered variants of that family. If an
        # offer reaches this point without resolving, it is not a member of
        # the requested family and must not leak into `unresolved_offers`.
        # This is generic family-scope handling; it contains no product or
        # retailer-specific exceptions.
        family_resolver = getattr(PRODUCT_MATCHER, "_family_for_query", None)
        if callable(family_resolver):
            try:
                requested_family = family_resolver(str(query or "").strip())
            except Exception as exc:
                requested_family = None
                print(
                    f"PRODUCT_MATCHER_FAMILY_SCOPE_ERROR: {type(exc).__name__}: {exc}",
                    flush=True,
                )
            if requested_family is not None:
                output.update({
                    "_match_status": "rejected",
                    "_reject_reason": "outside_query_family",
                    "catalog_id": None,
                    "canonical_name": None,
                })
                return output

        output.update({
            "_match_status": "unresolved",
            "catalog_id": None,
            "canonical_name": None,
        })
        return output

    # The central matcher returns the resolved offer directly.  Do not replace
    # the retailer's raw brand/name fields; canonical identity is exposed in
    # its dedicated canonical_* fields.
    output.update(match)
    output["_match_status"] = "matched"

    if not output.get("catalog_id"):
        output["_match_status"] = "unresolved"

    if output.get("canonical_brand") and not output.get("_canonical_brand"):
        output["_canonical_brand"] = output.get("canonical_brand")

    output["match_confidence"] = output.get("confidence")
    return output

_NON_FRAGRANCE_TITLE_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:gift\s*set|set\s*regalo|coffret|cofre|estuche|"
    r"discovery\s*set|sample(?:s)?|sample\s*set|mystery\s*box|beauty\s*box|"
    r"gift\s*box|bundle|pack\s*regalo|duo|trio|kit|case|set|"
    r"decant(?:s)?|tester(?:s)?|testeur(?:s)?|probe(?:s)?|proben|proef(?:je|jes)?|pröbchen|échantillon(?:s)?|muestra(?:s)?)(?:[^a-z0-9]|$)",
    re.I,
)

_NON_FRAGRANCE_CATEGORY_RE = re.compile(
    r"(?:cosmetic|cosmetics|make[- ]?up|maquill|skincare|skin\s*care|"
    r"hair\s*care|shampoo|conditioner|body\s*care|bath|shower|"
    r"cream|crema|lotion|serum|mascara|lipstick|candle|vela|home|"
    r"accessor|accessori|jewell|joyer|watch|reloj|bag|bolso|"
    r"toiletr|wallet|cartera|brush|pennello|sponge|esponja|"
    r"deodorant|desodorante|aftershave|rasage|soap|jabon)(?:[^a-z0-9]|$)",
    re.I,
)


def _is_non_fragrance_offer(item):
    """Reject generic non-perfume commercial items before matching/publication.

    This is intentionally category-based, never product-specific. Bundles,
    gift sets, mystery boxes and clearly non-fragrance categories are not
    individual perfume offers, so they must not enter either the matcher or
    the unresolved-offers UI.
    """
    if not isinstance(item, dict):
        return True

    for key in ("is_fragrance", "is_perfume"):
        if key in item and item.get(key) is False:
            return True

    category_values = []
    for key in (
        "product_type", "productType", "category", "category_name",
        "categoryName", "department", "type", "product_category",
        "productCategory",
    ):
        value = item.get(key)
        if value not in (None, ""):
            category_values.append(str(value))

    category_text = " ".join(category_values)
    if category_text and _NON_FRAGRANCE_CATEGORY_RE.search(category_text):
        return True

    title_parts = []
    for key in ("name", "title", "raw_name", "_raw_name", "canonical_name"):
        value = item.get(key)
        if value not in (None, ""):
            title_parts.append(str(value))
    title_text = " ".join(title_parts)

    return bool(
        _NON_FRAGRANCE_TITLE_RE.search(title_text)
        or _NON_FRAGRANCE_CATEGORY_RE.search(title_text)
    )


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

    # Compute the normalized retailer label unconditionally. The nested
    # generic cleanup below also runs when a scraper does not provide a
    # brand, so this value must never depend on ``raw_brand`` being present.
    normalized_store_label = "".join(
        str(STORE_LABELS.get(machine_store, machine_store) or "")
        .lower()
        .replace("-", " ")
        .split()
    )

    # Some retailer APIs expose the retailer/vendor name in the ``brand``
    # field rather than the actual product brand. That is commercial source
    # metadata, not product identity. Do not let a store name become a hard
    # brand constraint for the central matcher; the original value remains
    # available in ``_raw_brand`` for diagnostics/provenance.
    if raw_brand:
        normalized_brand = "".join(
            raw_brand.lower().replace("-", " ").split()
        )
        if normalized_brand == normalized_store_label:
            result["brand"] = ""
            source = result.get("source")
            if isinstance(source, dict):
                source = dict(source)
                source_brand = str(source.get("source_brand") or source.get("brand") or "").strip()
                normalized_source_brand = " ".join(source_brand.lower().replace("-", " ").split())
                if normalized_source_brand == normalized_store_label:
                    source["source_brand"] = ""
                    if "brand" in source:
                        source["brand"] = ""
                result["source"] = source

    # Remove retailer-vendor brand metadata from nested source structures too.
    # Some scraper payloads expose the same vendor under source/source_brand
    # or source/brand; ProductMatcher may legitimately fall back to those
    # fields when the top-level brand is empty. This cleanup is generic and
    # applies only when the nested value is the retailer label itself.
    def _clean_retailer_brand_metadata(value):
        if isinstance(value, dict):
            cleaned = dict(value)
            for key in ("source_brand", "brand", "manufacturer"):
                current = str(cleaned.get(key) or "").strip()
                if current:
                    normalized_current = "".join(
                        current.lower().replace("-", " ").split()
                    )
                    if normalized_current == normalized_store_label:
                        cleaned[key] = ""
            for key, nested in list(cleaned.items()):
                if isinstance(nested, (dict, list, tuple)):
                    cleaned[key] = _clean_retailer_brand_metadata(nested)
            return cleaned
        if isinstance(value, list):
            return [_clean_retailer_brand_metadata(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_clean_retailer_brand_metadata(item) for item in value)
        return value

    if isinstance(result.get("source"), (dict, list, tuple)):
        result["source"] = _clean_retailer_brand_metadata(result.get("source"))

    # Keep the retailer's raw name untouched for provenance, but remove a generic
    # retailer-label prefix from the normalized product name when a source card
    # has prepended its own shop name. This is source normalization only.
    retailer_label = str(STORE_LABELS.get(machine_store, machine_store) or "").strip()
    if retailer_label and result.get("name"):
        prefix_re = re.compile(rf"^\s*{re.escape(retailer_label)}\s*(?:[-–—:|]\s*)+", re.I)
        cleaned_name = prefix_re.sub("", str(result.get("name") or "").strip(), count=1).strip()
        if cleaned_name:
            result["name"] = cleaned_name

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

    # Generic structured-offer fallback. Some scrapers expose the same
    # commercial price inside an ``offer`` object as well as (or instead of)
    # the legacy top-level fields. Flatten only the generic price fields here;
    # no product/store-specific rule is involved.
    nested_offer = result.get("offer")
    if isinstance(nested_offer, dict):
        if result.get("price") in (None, ""):
            nested_price = nested_offer.get("price")
            if nested_price not in (None, ""):
                result["price"] = nested_price
        if result.get("price_num") in (None, ""):
            nested_price_num = nested_offer.get("price_num")
            if nested_price_num in (None, ""):
                nested_price_num = nested_offer.get("price")
            parsed_nested = _safe_float(nested_price_num)
            if parsed_nested is not None:
                result["price_num"] = parsed_nested

    if "price_num" not in result or result.get("price_num") in (None, ""):
        parsed = _safe_float(result.get("price"))

        if parsed is not None:
            result["price_num"] = parsed

    # Never expose a zero/negative retailer price as a real commercial price.
    # A missing/invalid price remains unknown and must not become 0,00 €.
    try:
        price_num = float(result.get("price_num"))
    except (TypeError, ValueError):
        price_num = None

    if price_num is not None and price_num <= 0:
        result["price_num"] = None
        result["price"] = None

    return result

def result_key(item):
    """Build one stable commercial-offer key.

    The central matcher owns catalog identity. When a catalog_id is available,
    it is therefore the strongest generic signal for collapsing duplicate
    listings from the same retailer and format. URL/product-id/name remain
    fallbacks for unresolved or legacy rows.
    """
    store = _normalise_store(item.get('store') or item.get('shop'), '')
    catalog_id = str(item.get('catalog_id') or '').strip().lower()
    url = str(item.get('url') or item.get('product_url') or '').strip().lower()
    product_id = str(item.get('store_product_id') or item.get('product_id') or item.get('sku') or '').strip().lower()
    name = ' '.join(str(item.get('name') or item.get('title') or '').split()).lower()
    size = _safe_float(item.get('size_ml'))
    identity_key = catalog_id or url or product_id or name
    return (store, identity_key, round(size,3) if size is not None else '')

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
    # Canonical identity must win over retailer/source brand metadata.
    # The matcher resolves canonical_brand separately from the retailer's
    # raw brand; using item["brand"] first caused inconsistent display.
    canonical_brand = (
        item.get("canonical_brand")
        or item.get("brand")
        or item.get("manufacturer")
    )

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
            # Final generic publication guard: non-fragrance commercial rows
            # (samples, testers, gift sets, bundles, cosmetics, etc.) must
            # never enter public offer groups even if an upstream path marked
            # them as matched.
            if _is_non_fragrance_offer(offer):
                continue

            catalog_id = str(
                offer.get("catalog_id")
            ).strip()

            if catalog_id not in groups:
                groups[catalog_id] = {
                    "catalog_id": catalog_id,
                    "brand": (
                        offer.get("canonical_brand")
                        or offer.get("brand")
                    ),
                    "canonical_brand": (
                        offer.get("canonical_brand")
                        or offer.get("brand")
                    ),
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
    return {'store':store,'status':status,'elapsed':round(elapsed,3),'count':0,'results':[],'error':error,'verified':False}

def load_scraper(store): return importlib.import_module(f'scrapers.{store}.scraper')

def normalise_report(raw):
    """Normalize the native scraper contract without inventing a match."""
    if isinstance(raw, dict):
        results = raw.get('results')
        if results is None: results = raw.get('products')
        if not isinstance(results, list): results = []
        status = str(raw.get('status') or '').strip().lower()
        if status not in {'success','partial','error','timeout','blocked','unavailable'}: status = 'success'
        details = raw.get('details') or {}
        verified = bool(raw.get('verified')) if 'verified' in raw else (status == 'success')
        if isinstance(details, dict) and 'verified' in details: verified = bool(details.get('verified'))
        return {'status':status,'verified':verified,'results':[r for r in results if isinstance(r,dict)],'error':raw.get('error'),'details':details}
    if isinstance(raw, tuple): raw=list(raw)
    if isinstance(raw, list):
        rows=[r for r in raw if isinstance(r,dict)]
        return {
            'status':'success' if rows else 'unavailable',
            'verified':bool(rows),
            'results':rows,
            'error':None if rows else 'legacy_scraper_returned_unverified_empty_list',
            'details':{},
        }
    if raw is None: return {'status':'error','verified':False,'results':[],'error':'scraper_returned_none','details':{}}
    try: values=list(raw)
    except TypeError: values=[]
    rows=[r for r in values if isinstance(r,dict)]
    return {'status':'success','verified':bool(rows),'results':rows,'error':None,'details':{}}

WORKER_CODE = r'''
import importlib, json, sys
store=sys.argv[1]; query=sys.argv[2]
def emit(event, **payload):
    print(json.dumps({'event':event, **payload},ensure_ascii=False,default=str),flush=True)

def normalise_report(raw):
    if isinstance(raw, dict):
        results = raw.get('results')
        if results is None:
            results = raw.get('products')
        if not isinstance(results, list):
            results = []
        status = str(raw.get('status') or '').strip().lower()
        if status not in {'success','partial','error','timeout','blocked','unavailable'}:
            status = 'success'
        details = raw.get('details') or {}
        verified = bool(raw.get('verified')) if 'verified' in raw else (status == 'success')
        if isinstance(details, dict) and 'verified' in details:
            verified = bool(details.get('verified'))
        return {'status':status,'verified':verified,'results':[r for r in results if isinstance(r,dict)],'error':raw.get('error'),'details':details}
    if isinstance(raw, (list, tuple)):
        rows=[r for r in raw if isinstance(r,dict)]
        return {
            'status':'success' if rows else 'unavailable',
            'verified':bool(rows),
            'results':rows,
            'error':None if rows else 'legacy_scraper_returned_unverified_empty_list',
            'details':{},
        }
    if raw is None:
        return {'status':'error','verified':False,'results':[],'error':'scraper_returned_none','details':{}}
    try:
        values=list(raw)
    except TypeError:
        values=[]
    rows=[r for r in values if isinstance(r,dict)]
    return {'status':'success','verified':bool(rows),'results':rows,'error':None,'details':{}}

try:
    module=importlib.import_module(f'scrapers.{store}.scraper')
    stream=getattr(module,'search_stream',None)
    if callable(stream):
        rows=[]
        def on_result(row):
            if isinstance(row,dict):
                rows.append(row); emit('result',row=row)
        returned=stream(query,on_result)
        # The definitive scraper contract requires search_stream() to return
        # its report even when callback delivery is used. None is therefore a
        # contract violation, not a verified empty search.
        if returned is None:
            raise RuntimeError('scraper_search_stream_returned_none')
        report=normalise_report(returned)
        if report['results'] and not rows:
            for row in report['results']: emit('result',row=row)
        emit('done',status=report['status'],verified=bool(report.get('verified')),error=report.get('error'),details=report.get('details') or {},count=len(rows) if rows else len(report['results']),streaming=True)
    else:
        search=getattr(module,'search',None)
        if not callable(search): raise RuntimeError(f'scraper {store} non espone search(query)')
        report=normalise_report(search(query))
        for row in report['results']: emit('result',row=row)
        emit('done',status=report['status'],verified=bool(report.get('verified')),error=report.get('error'),details=report.get('details') or {},count=len(report['results']),streaming=False)
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

def _run_store_subprocess_once(store, query, on_result=None, timeout_override=None, cancel_event=None):
    started=time.monotonic()
    timeout=float(timeout_override) if timeout_override is not None else STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS)
    env=os.environ.copy(); current=env.get('PYTHONPATH',''); env['PYTHONPATH']=str(BASE_DIR)+(os.pathsep+current if current else '')
    process=None; rows=[]; worker_status=None; worker_verified=None; worker_error=None; worker_details={}
    try:
        _runtime_diag_event('worker_spawn_attempt', store=store, query=str(query), timeout=timeout)
        process=subprocess.Popen([sys.executable,'-u','-c',WORKER_CODE,store,query],cwd=str(BASE_DIR),env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=False,bufsize=0,start_new_session=(os.name!='nt'))
        deadline=time.monotonic()+timeout; stdout_buffer=b''
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _runtime_diag_event('worker_cancelled', store=store, pid=getattr(process,'pid',None))
                _kill_process_tree(process)
                try: process.communicate(timeout=2)
                except Exception: pass
                return _empty_report(store,status='cancelled',elapsed=round(time.monotonic()-started,3),error='search_cancelled') | {'verified':False}
            remaining=deadline-time.monotonic()
            if remaining<=0: raise subprocess.TimeoutExpired(process.args,timeout)
            chunk=b''
            if process.stdout is not None:
                if os.name!='nt':
                    import select
                    ready,_,_=select.select([process.stdout],[],[],min(0.25,remaining))
                    if ready:
                        try: chunk=os.read(process.stdout.fileno(),65536)
                        except (BlockingIOError,OSError): chunk=b''
                else:
                    try: chunk=process.stdout.read1(65536)
                    except (AttributeError,BlockingIOError): chunk=b''
            if chunk:
                stdout_buffer+=chunk
                while b'\n' in stdout_buffer:
                    raw_line,stdout_buffer=stdout_buffer.split(b'\n',1)
                    try: event=json.loads(raw_line.decode('utf-8','replace').strip())
                    except (json.JSONDecodeError,UnicodeDecodeError): continue
                    if not isinstance(event,dict): continue
                    kind=event.get('event')
                    if kind=='result' and isinstance(event.get('row'),dict):
                        prepared=clean_result(event['row'],store)
                        if prepared is None: continue
                        # ScentHunter searches individual perfumes only.
                        # Generic non-fragrance commercial items (sets, boxes,
                        # bundles, cosmetics, accessories, etc.) are discarded
                        # before ProductMatcher and therefore can never appear
                        # in either results or unresolved_offers.
                        if _is_non_fragrance_offer(prepared):
                            continue
                        resolved=_resolve_offer_identity(prepared,query)
                        if resolved is None: continue
                        if resolved.get('_match_status') == 'rejected':
                            continue
                        if _is_non_fragrance_offer(resolved):
                            continue
                        rows.append(resolved)
                        if callable(on_result):
                            try:
                                on_result(resolved)
                            except Exception:
                                pass
                    elif kind=='done':
                        worker_status=str(event.get('status') or 'success').strip().lower()
                        worker_verified=bool(event.get('verified')) if 'verified' in event else None
                        worker_error=event.get('error')
                        if isinstance(event.get('details'),dict): worker_details=event['details']
                    elif kind=='error':
                        worker_status='error'; worker_verified=False; worker_error=str(event.get('error') or 'worker_error')
            if process.poll() is not None:
                if process.stdout is not None and os.name!='nt':
                    try:
                        while True:
                            tail=os.read(process.stdout.fileno(),65536)
                            if not tail: break
                            stdout_buffer+=tail
                    except (BlockingIOError,OSError): pass
                break
        if stdout_buffer.strip():
            try: event=json.loads(stdout_buffer.decode('utf-8','replace').strip())
            except (json.JSONDecodeError,UnicodeDecodeError): event=None
            if isinstance(event,dict):
                if event.get('event')=='done':
                    worker_status=str(event.get('status') or 'success').strip().lower()
                    worker_verified=bool(event.get('verified')) if 'verified' in event else None
                    worker_error=event.get('error')
                    if isinstance(event.get('details'),dict): worker_details=event['details']
                elif event.get('event')=='error':
                    worker_status='error'; worker_verified=False; worker_error=str(event.get('error') or 'worker_error')
        rc=process.wait(timeout=1); elapsed=round(time.monotonic()-started,3)
        if rc!=0 and worker_status not in {'success','partial'}:
            return {'store':store,'status':worker_status or 'error','elapsed':elapsed,'count':len(rows),'results':rows,'error':worker_error or f'worker_exit_{rc}','details':worker_details,'verified':False}
        status=worker_status or ('success' if rows else 'error')
        verified=bool(worker_verified) if worker_verified is not None else bool(rows)
        # A verified empty result is a real NOT_FOUND. Keep the distinction
        # explicit so technical failures can never become absence.
        if status == 'success' and verified and not rows:
            public_status='no_match'
        elif status == 'success' and rows:
            public_status='ok'
        else:
            public_status=status
        return {'store':store,'status':public_status,'elapsed':elapsed,'count':len(rows),'results':rows,'error':worker_error,'details':worker_details,'verified':verified}
    except subprocess.TimeoutExpired:
        _runtime_diag_event('worker_timeout', store=store, pid=getattr(process,'pid',None), timeout=timeout)
        if process is not None:
            _kill_process_tree(process)
            try: process.communicate(timeout=2)
            except Exception: pass
        return _empty_report(store,status='timeout',elapsed=round(time.monotonic()-started,3),error=f'store_timeout_{timeout:.0f}s') | {'verified':False}
    except Exception as exc:
        _runtime_diag_event('worker_exception', store=store, pid=getattr(process,'pid',None), error=f'{type(exc).__name__}: {exc}')
        if process is not None:
            _kill_process_tree(process)
            try: process.communicate(timeout=1)
            except Exception: pass
        return _empty_report(store,status='error',elapsed=round(time.monotonic()-started,3),error=f'{type(exc).__name__}: {exc}') | {'verified':False}


def _run_store_subprocess(store, query, on_result=None, cancel_event=None):
    """Retry only an unverified search result, never a technical failure.

    A technical failure (timeout/error/blocked/unavailable/cancelled) is already
    an authoritative store failure for this attempt. Retrying it here can make
    one store occupy its lane for another 45 seconds and, with the 2-slot light
    lane, starve the other stores until the 125s job deadline cancels them.
    """
    first=_run_store_subprocess_once(store,query,on_result=on_result,cancel_event=cancel_event)
    fs=first.get('status'); fv=bool(first.get('verified')); fc=int(first.get('count') or 0)

    # IMPORTANT: technical failures are NOT retried. This restores the old
    # lifecycle behaviour and prevents a slow/blocked store from monopolising
    # a lane and cascading cancellation into other stores.
    if fs in {'timeout','error','blocked','unavailable','cancelled'}:
        first['attempts']=1
        return first

    if fv and (fs in {'ok','no_match'} or (fs=='partial' and fc>0)):
        first['attempts']=1
        return first

    # Only ambiguous/unverified search outcomes are eligible for one retry.
    print(f"STORE RETRY store={store} query={query!r} reason={fs} verified={fv} count={fc}",flush=True)
    base_timeout=STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS)
    retry_timeout=max(12.0,min(base_timeout*0.75,45.0))
    second=_run_store_subprocess_once(store,query,on_result=on_result,timeout_override=retry_timeout,cancel_event=cancel_event)
    second['attempts']=2; second['first_attempt_status']=fs; second['first_attempt_verified']=fv
    ss=second.get('status'); sv=bool(second.get('verified')); sc=int(second.get('count') or 0)

    if ss=='no_match' and sv:
        second['status']='no_match'; second['verified']=True; second['error']=None; return second
    if ss=='ok' and sv: return second
    if ss=='partial' and sv and sc>0: return second

    second['verified']=False
    if ss not in {'error','timeout','blocked','unavailable','cancelled'}:
        second['status']='unavailable'
    if not second.get('error'):
        second['error']=f"store_unverified_after_retry:{second.get('status')}"
    return second

def _run_controlled_store(store,query,on_report,on_result=None,cancel_event=None):
    _runtime_diag_event('store_thread_start', store=store, query=str(query))
    print(f'STORE START store={store} query={query!r}',flush=True)
    semaphore=LIGHT_SEMAPHORE; lane='light'
    if store in BROWSER_STORES: semaphore=BROWSER_SEMAPHORE; lane='browser'
    elif store in NETWORK_HEAVY_STORES: semaphore=NETWORK_SEMAPHORE; lane='network'
    wait=time.monotonic()
    if semaphore is not None:
        acquired=False
        wait_deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
        while not acquired:
            if cancel_event is not None and cancel_event.is_set():
                on_report(_empty_report(store,status='cancelled',elapsed=round(time.monotonic()-wait,3),error='search_cancelled') | {'verified':False})
                return
            acquired=semaphore.acquire(timeout=min(0.25,max(0.0,wait_deadline-time.monotonic())))
            if time.monotonic() >= wait_deadline and not acquired:
                break
        if not acquired:
            _runtime_diag_event('store_lane_timeout', store=store, lane=lane)
            report=_empty_report(store,error=f'{lane}_lane_unavailable')
            print(f'STORE TIMEOUT store={store} timeout=lane_wait',flush=True); on_report(report); return
        waited=round(time.monotonic()-wait,3)
        _runtime_diag_event('store_lane_acquired', store=store, lane=lane, waited=waited, available=getattr(semaphore,'_value',None))
        if waited>.1: print(f'STORE QUEUED store={store} lane={lane} waited={waited}',flush=True)
    try: report=_run_store_subprocess(store,query,on_result=on_result,cancel_event=cancel_event)
    finally:
        if semaphore is not None: semaphore.release()
    if report.get('status')=='error':
        if str(report.get('error','')).startswith('store_timeout_'): print(f"STORE TIMEOUT store={store} timeout={report['error']}",flush=True)
        else: print(f"STORE ERROR store={store} error={report.get('error')}",flush=True)
    print(f"STORE END store={store} status={report.get('status')} elapsed={report.get('elapsed')} count={report.get('count')}",flush=True)
    _runtime_diag_event('store_thread_end', store=store, status=report.get('status'), elapsed=report.get('elapsed'), count=report.get('count'))
    on_report(report)

def _catalog_indexed_flags(stores):
    """Check whether each store has at least one active catalog URL.

    This is deliberately much cheaper than catalog_store_status(). It is used
    on the normal search path only to distinguish an indexed store with zero
    matching candidates from a store whose catalog is actually empty. It never
    joins store_urls with store_products and never calculates hydration state.
    """
    wanted = [str(store).strip() for store in (stores or []) if str(store).strip()]
    if not wanted or not callable(catalog_db):
        return {store: False for store in wanted}
    conn = None
    try:
        conn = catalog_db()
        flags = {}
        for store in wanted:
            row = conn.execute(
                'SELECT 1 FROM store_urls WHERE store=? AND active=1 LIMIT 1',
                (store,),
            ).fetchone()
            flags[store] = bool(row)
        return flags
    except Exception as exc:
        print(f'CATALOG INDEXED STATUS ERROR: {type(exc).__name__}: {exc}', flush=True)
        return {store: False for store in wanted}
    finally:
        if conn is not None:
            conn.close()


def _catalog_search_terms(query):
    """Build generic URL-discovery terms from the central ProductMatcher."""
    if PRODUCT_MATCHER is None:
        return [str(query or '').strip()] if str(query or '').strip() else []
    method = getattr(PRODUCT_MATCHER, 'catalog_search_terms', None)
    if callable(method):
        try:
            terms = method(str(query or '').strip()) or []
            return [str(term).strip() for term in terms if str(term or '').strip()]
        except Exception as exc:
            print(f'CATALOG_SEARCH_TERMS_ERROR: {type(exc).__name__}: {exc}', flush=True)
    return [str(query or '').strip()] if str(query or '').strip() else []


def _collect_catalog_reports_isolated(query, stores, on_report=None, on_result=None, cancel_event=None, job_id=None):
    """Primary catalog-first search path.

    Discovery is performed by catalog_engine, not by retailer search endpoints.
    ProductMatcher remains the only component allowed to decide identity.
    """
    started = time.monotonic()
    reports_by_store = {}
    if cancel_event is not None and cancel_event.is_set():
        return []

    terms = _catalog_search_terms(query)
    candidate_limit = min(128, max(64, len(terms) * 2)) if len(terms) > 1 else 64

    try:
        raw_rows = catalog_search_local(query, per_store=candidate_limit, search_terms=terms) if callable(catalog_search_local) else []
    except TypeError:
        raw_rows = catalog_search_local(query, per_store=candidate_limit) if callable(catalog_search_local) else []
    except Exception as exc:
        print(f'CATALOG SEARCH ERROR: {type(exc).__name__}: {exc}', flush=True)
        raw_rows = []

    # The catalog decides WHICH URLs are relevant. For the query-selected
    # candidates that are not hydrated yet, perform a short targeted fetch.
    # This is deliberately not retailer discovery and never calls a retailer
    # search endpoint. Background hydration continues independently.
    refreshed = []
    if callable(catalog_refresh_candidates):
        try:
            refresh_budget = min(8.0, max(0.25, float(os.environ.get(
                'CATALOG_REFRESH_BUDGET_SECONDS', '8'
            ))))
            refresh_deadline = started + refresh_budget
            requested = [
                row for row in raw_rows
                if isinstance(row, dict) and row.get('_needs_refresh')
            ]
            if requested:
                refreshed = catalog_refresh_candidates(
                    requested,
                    cancel_event=cancel_event,
                    deadline=refresh_deadline,
                    max_workers=min(8, max(1, len(stores))),
                ) or []
                print(
                    f'CATALOG TARGETED REFRESH requested={len(requested)} '
                    f'returned={len(refreshed)}',
                    flush=True,
                )
        except Exception as exc:
            print(
                f'CATALOG TARGETED REFRESH UNAVAILABLE: '
                f'{type(exc).__name__}: {exc}',
                flush=True,
            )

    refreshed_by_key = {}
    for item in refreshed:
        if not isinstance(item, dict):
            continue
        store_key = _normalise_store(item.get('store_key') or item.get('store'), '')
        url = str(item.get('url') or item.get('product_url') or '').strip()
        if store_key and url:
            item = dict(item)
            item['store_key'] = store_key
            item['store'] = STORE_LABELS.get(store_key, item.get('store') or store_key)
            item['shop'] = item['store']
            refreshed_by_key[(store_key, url)] = item

    grouped_raw = {store: [] for store in stores}
    pending_by_store = {store: 0 for store in stores}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        store_key = _normalise_store(row.get('store_key') or row.get('store') or row.get('shop'), '')
        url = str(row.get('url') or row.get('product_url') or '').strip()
        replacement = refreshed_by_key.get((store_key, url))
        item = replacement if replacement is not None else dict(row)
        if store_key not in grouped_raw:
            continue
        if replacement is None and item.get('_needs_refresh'):
            pending_by_store[store_key] = pending_by_store.get(store_key, 0) + 1
            continue
        item['store_key'] = store_key
        item['store'] = STORE_LABELS.get(store_key, item.get('store') or store_key)
        item['shop'] = item['store']
        grouped_raw[store_key].append(item)

    # Never call catalog_store_status() here. It performs a catalog-wide
    # LEFT JOIN to calculate hydration state and can contend with background
    # hydration writers on SQLite. We only need to know whether each store
    # has any active catalog URL, which is answered by a cheap indexed flag.
    indexed_flags = _catalog_indexed_flags(stores)
    indexed_total = sum(1 for store in stores if indexed_flags.get(store))

    # A completely empty catalog means the background bootstrap has not
    # indexed any store yet. Normal searches must wait for that bootstrap;
    # they must never trigger retailer discovery or the legacy live scraper.
    if not raw_rows and indexed_total <= 0:
        for store in stores:
            report = _empty_report(
                store,
                status='catalog_bootstrapping',
                elapsed=time.monotonic() - started,
                error='catalog_bootstrapping',
            ) | {
                'verified': False,
                'details': {
                    'source': 'persistent_catalog',
                    'authoritative': True,
                    'retryable': True,
                },
            }
            reports_by_store[store] = report
            if callable(on_report):
                on_report(report)
        return [reports_by_store[s] for s in stores]

    for store in stores:
        store_rows = grouped_raw.get(store, [])
        matched_rows = []
        unresolved_count = 0
        for raw in store_rows:
            if cancel_event is not None and cancel_event.is_set():
                break
            prepared = clean_result(raw, store)
            if prepared is None or _is_non_fragrance_offer(prepared):
                continue
            resolved = _resolve_offer_identity(prepared, query)
            if not isinstance(resolved, dict):
                continue
            if resolved.get('_match_status') == 'rejected':
                continue
            if _is_non_fragrance_offer(resolved):
                continue
            matched_rows.append(resolved)
            if resolved.get('_match_status') != 'matched' or not resolved.get('catalog_id'):
                unresolved_count += 1
            # Catalog-first search publishes the complete store batch through
            # on_report below. Do not aggregate once per product.

        # A store with candidate rows is necessarily indexed. For stores with
        # zero candidates, use the lightweight active-URL check above rather
        # than catalog_store_status(), so a real indexed store is reported as
        # verified/no_match instead of falsely becoming catalog_not_indexed.
        indexed = 1 if indexed_flags.get(store) else 0
        if store_rows:
            indexed = max(indexed, 1)
        fetched = len(store_rows)
        if matched_rows:
            status, verified, error = 'success', True, None
        elif pending_by_store.get(store, 0) > 0:
            status, verified, error = 'catalog_pending', False, 'product_page_refresh_pending'
        elif indexed > 0:
            status, verified, error = 'no_match', True, None
        else:
            status = str(status_info.get('status') or 'unavailable').lower()
            verified = False
            error = status_info.get('error') or 'catalog_not_indexed'

        report = {
            'store': store,
            'status': status,
            'verified': verified,
            'elapsed': round(time.monotonic() - started, 3),
            'count': len(matched_rows),
            'results': matched_rows,
            'error': error,
            'details': {
                'source': 'persistent_catalog',
                'candidate_count': len(store_rows) + pending_by_store.get(store, 0),
                'pending_refresh_count': pending_by_store.get(store, 0),
                'unresolved_count': unresolved_count,
                'indexed_urls': indexed,
                'fetched_products': fetched,
                'candidate_limit': candidate_limit,
                'search_terms_count': len(terms),
            },
        }
        reports_by_store[store] = report
        if callable(on_report):
            on_report(report)

    print(f'CATALOG SEARCH END query={query!r} candidates={len(raw_rows)} elapsed={round(time.monotonic() - started, 3)}', flush=True)
    return [reports_by_store[s] for s in stores if s in reports_by_store]


def collect_store_reports_isolated(query, stores, on_report=None, on_result=None, cancel_event=None, job_id=None):
    requested = list(stores)
    if CATALOG_ENGINE_AVAILABLE and callable(catalog_search_local):
        try:
            return _collect_catalog_reports_isolated(query, requested, on_report=on_report, on_result=on_result, cancel_event=cancel_event, job_id=job_id)
        except Exception as exc:
            # Normal search is catalog-only. Never fall back to the legacy live
            # scraper here: that path is what caused one slow search to occupy
            # the global job for minutes and block subsequent searches.
            print(f'CATALOG PRIMARY PATH ERROR: {type(exc).__name__}: {exc}', flush=True)
            error = f'catalog_search_error:{type(exc).__name__}:{exc}'
            reports = []
            for store in requested:
                report = _empty_report(store, status='error', elapsed=0.0, error=error) | {
                    'verified': False,
                    'details': {'source': 'persistent_catalog', 'authoritative': True},
                }
                reports.append(report)
                if callable(on_report):
                    on_report(report)
            return reports
    reports = {}
    lock = threading.Lock()
    threads = []

    def publish(report):
        with lock:
            reports[report['store']] = report
        if callable(on_report):
            on_report(report)

    for store in requested:
        t = threading.Thread(
            target=_run_controlled_store,
            args=(store, query, publish, on_result, cancel_event),
            daemon=True,
            name=f'scenthunter-store-{store}'
        )
        t.start()
        threads.append(t)

    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    for t in threads:
        t.join(timeout=max(0.0, deadline - time.monotonic()))

    unfinished = [
        t.name.rsplit('scenthunter-store-', 1)[-1]
        for t in threads
        if t.is_alive()
    ]

    if unfinished:
        print(f'SEARCH SUPERVISORS CANCELLING stores={unfinished}', flush=True)
        if cancel_event is not None:
            cancel_event.set()
        cancel_deadline = time.monotonic() + 3.0
        for t in threads:
            if t.is_alive():
                t.join(timeout=max(0.0, cancel_deadline - time.monotonic()))

    with lock:
        for store in unfinished:
            reports.setdefault(
                store,
                _empty_report(store, elapsed=JOB_TIMEOUT_SECONDS, error='job_timeout')
            )

    return [reports[s] for s in requested if s in reports]


JOBS={}; JOBS_LOCK=threading.Lock()

def _cancel_active_jobs(wait_timeout=2.5):
    """Request cancellation and wait briefly for active search jobs to finish.

    /search-start must remain responsive.  A previous search is cancelled first,
    but if its thread has not reached its done_event within the short handshake
    window, the caller must return ``busy`` rather than blocking the HTTP request.
    """
    _runtime_diag_event('cancel_active_jobs_enter')
    with JOBS_LOCK:
        active = [
            job for job in JOBS.values()
            if not job.get("completed") and not job.get("done_event", threading.Event()).is_set()
        ]

    if not active:
        _runtime_diag_event('cancel_active_jobs_no_active')
        return True

    for job in active:
        event = job.get("cancel_event")
        if event is not None:
            event.set()

    print(f"SEARCH CANCEL REQUEST active_jobs={len(active)}", flush=True)

    deadline = time.monotonic() + max(0.1, float(wait_timeout))
    all_done = True
    for job in active:
        done_event = job.get("done_event")
        if done_event is None:
            all_done = False
            continue
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0 or not done_event.wait(remaining):
            all_done = False
            print(
                f"SEARCH CANCEL HANDSHAKE PENDING job={job.get('job_id')} "
                f"waited={round(wait_timeout, 2)}",
                flush=True,
            )

    _runtime_diag_event('cancel_active_jobs_done', all_done=all_done, active_jobs=len(active))
    return all_done



def _new_job(query):
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "query": query,
            "started_at": time.time(),
            "completed": False,
            "status": "searching",
            "cancel_event": threading.Event(),
            "done_event": threading.Event(),
            "aggregate_lock": threading.Lock(),
            "offers": [],
            "results": [],
            "unresolved_offers": [],
            "comparisons": [],
            "errors": {},
            "stores": {},
            "store_threads": [],
            "thread": None,
        }
    return job_id


def _snapshot(job_id):
    # IMPORTANT: /search-status must remain a fast read-only endpoint.
    # Identity scope is computed once by _run_job and cached in the job.
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
                "errors": {"job": "job_not_found"},
                "stores": {},
            }

        query = job.get("query", "")
        completed = bool(job.get("completed"))
        status = job.get("status") or ("completed" if completed else "searching")
        results = list(job.get("results", []))
        offers = list(job.get("offers", []))
        unresolved_offers = list(job.get("unresolved_offers", []))
        errors = dict(job.get("errors", {}))
        stores = dict(job.get("stores", {}))
        dedupe_diagnostics = list(job.get("dedupe_diagnostics", []))
        identity_scope = list(job.get("identity_scope", []))

    # IMPORTANT: identity_scope is precomputed once by the job thread.
    # The HTTP status endpoint must remain fast and must NEVER invoke the
    # ProductMatcher/catalog scan on every 700 ms polling request.

    return {
        "job_id": job_id,
        "query": query,
        "completed": completed,
        "status": status,
        "count": len(results),
        "offer_count": len(offers),
        "results": results,
        "unresolved_offers": unresolved_offers,
        "identity_scope": identity_scope,
        "errors": errors,
        "stores": stores,
        "dedupe_diagnostics": dedupe_diagnostics,
    }

def _publish_result(job_id, row):
    """Append one offer to the job without doing expensive aggregation.

    Normal catalog-first searches already resolve identity before publishing.
    Re-running dedupe + ProductMatcher aggregation for every single offer made
    broad searches progressively slower and could keep the job alive for minutes.
    Final aggregation is performed once by _run_job after all stores finish.
    """
    if not isinstance(row, dict):
        return

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get("completed"):
            return
        if job.get("done_event") and job["done_event"].is_set():
            return
        job.setdefault("offers", []).append(row)


def _publish_store(job_id, report):
    """Publish one completed store report without running aggregation.

    Store reports are the authoritative batch boundary for the catalog-first
    search path. Keep this operation short: it only updates job state.
    Dedupe and identity grouping happen once, after all reports are returned.
    """
    if not isinstance(report, dict):
        return

    store = report.get("store")
    if not store:
        return

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get("completed"):
            return
        if job.get("done_event") and job["done_event"].is_set():
            return

        job["stores"][store] = {
            "status": report.get("status"),
            "verified": bool(report.get("verified")),
            "elapsed": report.get("elapsed", 0.0),
            "count": report.get("count", 0),
            "details": dict(report.get("details") or {}),
        }

        if report.get("error"):
            job["errors"][store] = report["error"]

        for item in report.get("results", []):
            if isinstance(item, dict):
                job.setdefault("offers", []).append(item)


def _run_job_impl(job_id, query):
    """Compatibility wrapper; the single authoritative lifecycle is _run_job."""
    return _run_job(job_id, query)

def _run_job(job_id, query):
    started = time.monotonic()
    print(f'SEARCH START job={job_id} query={query!r}', flush=True)

    job = None
    cancel_event = None
    store_threads = []
    elapsed = 0.0
    total = 0

    try:
        with JOBS_LOCK:
            current_job = JOBS.get(job_id)
            if current_job is None:
                print(f'SEARCH END job={job_id} elapsed={round(time.monotonic() - started, 3)} total=0 (job_not_found)', flush=True)
                return

            current_job["thread"] = threading.current_thread()
            cancel_event = current_job.get("cancel_event")
            job = current_job

        def on_report(r):
            _publish_store(job_id, r)

        def on_result(row):
            _publish_result(job_id, row)

        reports = collect_store_reports_isolated(
            query,
            STORES,
            on_report=on_report,
            on_result=on_result,
            cancel_event=cancel_event,
            job_id=job_id,
        )
        print(
            f"SEARCH COLLECTED job={job_id} query={query!r} "
            f"stores={len(reports or [])} elapsed={round(time.monotonic() - started, 3)}",
            flush=True,
        )

        # Registriamo i thread store nel job (per diagnosi / eventuali cleanup futuri)
        with JOBS_LOCK:
            if job is not None:
                job["store_threads"] = [
                    t for t in threading.enumerate()
                    if t.name.startswith("scenthunter-store-")
                ]

        # Copy only the mutable inputs while holding JOBS_LOCK.  Dedupe and
        # ProductMatcher aggregation can be expensive and MUST remain outside
        # the global job lock, otherwise /search-status and /search-start can
        # block behind matcher/catalog work.
        with JOBS_LOCK:
            if job is None:
                elapsed = round(time.monotonic() - started, 3)
                total = 0
            else:
                offers = list(job.get("offers", []))
                diagnostics = job.setdefault("dedupe_diagnostics", [])
                cancelled = bool(job.get("cancel_event") and job["cancel_event"].is_set())

        if job is not None:
            if cancel_event is not None and cancel_event.is_set():
                print(
                    f"SEARCH FINALIZE AFTER CANCEL job={job_id}",
                    flush=True,
                )

            # Aggregate exactly once after every store report has arrived.
            # This is the only expensive dedupe/identity pass for a normal
            # catalog-first search.
            deduped = dedupe_results(offers, diagnostics)
            grouped, unresolved = _aggregate_identity_results(deduped)

            elapsed = round(time.monotonic() - started, 3)

            with JOBS_LOCK:
                current_job = JOBS.get(job_id)
                if current_job is not None:
                    current_job["offers"] = deduped
                    current_job["results"] = grouped
                    current_job["unresolved_offers"] = unresolved
                    current_job["completed"] = True

                    # A completed job can still contain stores that were not
                    # authoritatively verified. This is NOT the same as a
                    # verified zero-result search, so expose a distinct final
                    # status instead of silently presenting "0 products".
                    store_issues = [
                        report for report in reports
                        if (
                            not bool(report.get("verified"))
                            or str(report.get("status") or "").lower()
                            in {"error", "timeout", "blocked", "unavailable"}
                        )
                    ]

                    if cancelled:
                        # A cancellation can race with already-published store
                        # results. Never describe a non-empty result set as
                        # "cancelled (no results)".
                        current_job["status"] = (
                            "cancelled_with_results"
                            if grouped
                            else "cancelled"
                        )
                    elif store_issues:
                        current_job["status"] = "completed_with_store_issues"
                    else:
                        current_job["status"] = "completed"

                    current_job["store_issue_count"] = len(store_issues)
                    current_job["elapsed"] = elapsed
                    total = len(grouped)
                else:
                    total = 0

    except Exception as exc:
        print(f'SEARCH ERROR job={job_id} {type(exc).__name__}: {exc}', flush=True)
        with JOBS_LOCK:
            if job is not None:
                job["completed"] = True
                job["status"] = "error"
                job.setdefault("errors", {})["job"] = f"{type(exc).__name__}: {exc}"
                job["elapsed"] = round(time.monotonic() - started, 3)
                elapsed = job["elapsed"]
                total = len(job.get("results", []))
    finally:
        # Finalizzazione definitiva: done_event
        with JOBS_LOCK:
            if job is not None:
                done_event = job.get("done_event")
                if done_event is not None:
                    done_event.set()

        print(f'SEARCH END job={job_id} elapsed={elapsed} total={total}', flush=True)


@app.get('/diagnostic/matcher')
def diagnostic_matcher(store: str, q: str):
    """Targeted diagnostic: raw scraper -> clean_result -> ProductMatcher.

    Diagnostic only. It does not publish offers into a search job and does not
    alter the normal aggregation pipeline.
    """
    machine_store = _normalise_store(store, store)
    query = str(q or '').strip()

    if machine_store not in STORES:
        return {
            'ok': False,
            'diagnostic': 'scraper -> clean_result -> ProductMatcher',
            'store': machine_store,
            'query': query,
            'error': f'unknown_store:{machine_store}',
        }
    if not query:
        return {
            'ok': False,
            'diagnostic': 'scraper -> clean_result -> ProductMatcher',
            'store': machine_store,
            'query': query,
            'error': 'missing_query',
        }

    raw_rows = []
    stream_return_type = None
    stream_error = None

    try:
        module = importlib.import_module(f'scrapers.{machine_store}.scraper')
        stream = getattr(module, 'search_stream', None)
        if callable(stream):
            def on_result(row):
                if isinstance(row, dict):
                    raw_rows.append(dict(row))
            returned = stream(query, on_result)
            stream_return_type = type(returned).__name__
            if returned is not None and not raw_rows:
                if isinstance(returned, dict):
                    candidate_rows = returned.get('results')
                    if candidate_rows is None:
                        candidate_rows = returned.get('products')
                    if isinstance(candidate_rows, list):
                        raw_rows.extend(r for r in candidate_rows if isinstance(r, dict))
                elif isinstance(returned, (list, tuple)):
                    raw_rows.extend(r for r in returned if isinstance(r, dict))
                else:
                    try:
                        raw_rows.extend(r for r in list(returned) if isinstance(r, dict))
                    except TypeError:
                        pass
        else:
            search = getattr(module, 'search', None)
            if not callable(search):
                raise RuntimeError(f'scraper {machine_store} non espone search/search_stream')
            returned = search(query)
            stream_return_type = type(returned).__name__
            if isinstance(returned, dict):
                candidate_rows = returned.get('results')
                if candidate_rows is None:
                    candidate_rows = returned.get('products')
                if isinstance(candidate_rows, list):
                    raw_rows.extend(r for r in candidate_rows if isinstance(r, dict))
            elif isinstance(returned, (list, tuple)):
                raw_rows.extend(r for r in returned if isinstance(r, dict))
            else:
                try:
                    raw_rows.extend(r for r in list(returned) if isinstance(r, dict))
                except TypeError:
                    pass
    except Exception as exc:
        stream_error = f'{type(exc).__name__}: {exc}'

    matched = []
    rejected = []
    unresolved = []
    clean_errors = []

    def compact(item):
        return {
            'name': item.get('name') or item.get('title'),
            'brand': item.get('brand'),
            '_raw_brand': item.get('_raw_brand'),
            'price': item.get('price'),
            'price_num': item.get('price_num'),
            'size_ml': item.get('size_ml'),
            'url': item.get('url') or item.get('product_url'),
            'availability': item.get('availability'),
            'match_status': item.get('_match_status'),
            'match_method': item.get('match_method'),
            'match_score': item.get('match_score'),
            'confidence': item.get('confidence'),
            'catalog_id': item.get('catalog_id'),
            'canonical_name': item.get('canonical_name'),
            'canonical_brand': item.get('canonical_brand'),
            'canonical_image': item.get('canonical_image'),
            'image': item.get('image'),
            'image_url': item.get('image_url'),
            'retailer_image': item.get('image') or item.get('image_url'),
            'family': item.get('family'),
            'variant': item.get('variant'),
            'matched_alias': item.get('matched_alias'),
            'match_error': item.get('_match_error'),
        }

    for index, raw in enumerate(raw_rows):
        try:
            prepared = clean_result(raw, machine_store)
        except Exception as exc:
            clean_errors.append({
                'index': index,
                'error': f'{type(exc).__name__}: {exc}',
                'raw': raw,
            })
            continue
        if prepared is None:
            clean_errors.append({'index': index, 'error': 'clean_result_returned_none'})
            continue

        resolved = _resolve_offer_identity(prepared, query)
        if not isinstance(resolved, dict):
            rejected.append({'index': index, **compact(prepared)})
            continue

        payload = {'index': index, **compact(resolved)}
        if resolved.get('_match_status') == 'matched' and resolved.get('catalog_id'):
            matched.append(payload)
        elif resolved.get('_match_status') == 'rejected':
            rejected.append(payload)
        else:
            unresolved.append(payload)

    return {
        'ok': stream_error is None,
        'diagnostic': 'scraper -> clean_result -> ProductMatcher',
        'store': machine_store,
        'query': query,
        'stream_return_type': stream_return_type,
        'stream_error': stream_error,
        'identity_scope_count': len(_identity_scope(query)),
        'raw_count': len(raw_rows),
        'matched_count': len(matched),
        'rejected_count': len(rejected),
        'unresolved_count': len(unresolved),
        'clean_error_count': len(clean_errors),
        'matched': matched,
        'rejected': rejected,
        'unresolved': unresolved,
        'clean_errors': clean_errors,
    }


@app.get('/diagnostic/match-offer')
def diagnostic_match_offer(
    store: str,
    q: str,
    name: str,
    brand: str = '',
    url: str = '',
    size_ml: str = '',
):
    """Instant, network-free identity diagnostic.

    This endpoint deliberately bypasses scraper discovery. It feeds one
    controlled offer through clean_result -> ProductMatcher so identity bugs
    can be isolated from sitemap/search/network problems.
    """
    machine_store = _normalise_store(store, store)
    query = str(q or '').strip()
    raw_offer = {
        'store': machine_store,
        'name': str(name or '').strip(),
        'brand': str(brand or '').strip(),
        'url': str(url or '').strip(),
    }
    if str(size_ml or '').strip():
        raw_offer['size_ml'] = str(size_ml).strip()

    if machine_store not in STORES:
        return {
            'ok': False,
            'diagnostic': 'controlled offer -> clean_result -> ProductMatcher',
            'error': f'unknown_store:{machine_store}',
            'offer': raw_offer,
        }
    if not query:
        return {
            'ok': False,
            'diagnostic': 'controlled offer -> clean_result -> ProductMatcher',
            'error': 'missing_query',
            'offer': raw_offer,
        }
    if not raw_offer['name']:
        return {
            'ok': False,
            'diagnostic': 'controlled offer -> clean_result -> ProductMatcher',
            'error': 'missing_name',
            'offer': raw_offer,
        }

    try:
        prepared = clean_result(raw_offer, machine_store)
        if prepared is None:
            return {
                'ok': False,
                'diagnostic': 'controlled offer -> clean_result -> ProductMatcher',
                'error': 'clean_result_returned_none',
                'offer': raw_offer,
            }

        resolved = _resolve_offer_identity(prepared, query)
        return {
            'ok': True,
            'diagnostic': 'controlled offer -> clean_result -> ProductMatcher',
            'store': machine_store,
            'query': query,
            'input': {
                'name': prepared.get('name'),
                'brand': prepared.get('brand'),
                'url': prepared.get('url'),
                'size_ml': prepared.get('size_ml'),
            },
            'result': {
                'name': resolved.get('name') or resolved.get('title'),
                'brand': resolved.get('brand'),
                '_raw_brand': resolved.get('_raw_brand'),
                'url': resolved.get('url') or resolved.get('product_url'),
                'size_ml': resolved.get('size_ml'),
                'match_status': resolved.get('_match_status'),
                'reject_reason': resolved.get('_reject_reason'),
                'match_method': resolved.get('match_method'),
                'match_score': resolved.get('match_score'),
                'confidence': resolved.get('confidence'),
                'catalog_id': resolved.get('catalog_id'),
                'canonical_name': resolved.get('canonical_name'),
                'canonical_brand': resolved.get('canonical_brand'),
                'canonical_image': resolved.get('canonical_image'),
                'image': resolved.get('image'),
                'image_url': resolved.get('image_url'),
                'retailer_image': resolved.get('image') or resolved.get('image_url'),
                'family': resolved.get('family'),
                'variant': resolved.get('variant'),
            } if isinstance(resolved, dict) else None,
        }
    except Exception as exc:
        return {
            'ok': False,
            'diagnostic': 'controlled offer -> clean_result -> ProductMatcher',
            'error': f'{type(exc).__name__}: {exc}',
            'offer': raw_offer,
        }


@app.get('/diagnostic/scraper-offer-compare')
def diagnostic_scraper_offer_compare(store: str, q: str, url: str):
    """Read-only differential diagnostic for one real scraper product URL.

    Runs the exact deployed scraper path, then compares the complete cleaned
    offer with a minimal offer and with versions where one top-level field is
    removed. It never publishes offers and never changes normal search logic.
    """
    machine_store = _normalise_store(store, store)
    query = str(q or '').strip()
    product_url = str(url or '').strip()
    diagnostic_name = 'exact scraper product URL -> product_json -> make_item -> clean_result -> differential ProductMatcher'

    if machine_store not in STORES:
        return {'ok': False, 'diagnostic': diagnostic_name, 'error': f'unknown_store:{machine_store}'}
    if not query:
        return {'ok': False, 'diagnostic': diagnostic_name, 'error': 'missing_query'}
    if not product_url:
        return {'ok': False, 'diagnostic': diagnostic_name, 'error': 'missing_url'}

    session = None

    def match_snapshot(offer):
        if not isinstance(offer, dict) or PRODUCT_MATCHER is None:
            return {'match_status': 'unavailable', 'catalog_id': None, 'canonical_name': None,
                    'canonical_brand': None, 'match_method': None, 'match_score': None}
        try:
            match = PRODUCT_MATCHER.match(offer, query)
            if not isinstance(match, dict):
                return {'match_status': 'unresolved', 'catalog_id': None, 'canonical_name': None,
                        'canonical_brand': None, 'match_method': None, 'match_score': None}
            return {'match_status': 'matched', 'catalog_id': match.get('catalog_id'),
                    'canonical_name': match.get('canonical_name'),
                    'canonical_brand': match.get('canonical_brand'),
                    'match_method': match.get('match_method'), 'match_score': match.get('match_score')}
        except Exception as exc:
            return {'match_status': 'error', 'error': f'{type(exc).__name__}: {exc}'}

    def compact(offer):
        return {
            'keys': sorted(str(k) for k in offer.keys()),
            'name': offer.get('name'), 'brand': offer.get('brand'),
            '_raw_brand': offer.get('_raw_brand'), 'url': offer.get('url'),
            'size_ml': offer.get('size_ml'), 'store': offer.get('store'),
            'source': offer.get('source'), 'identity': offer.get('identity'),
            'attributes': offer.get('attributes'), 'offer': offer.get('offer'),
            'provenance': offer.get('provenance'),
        }

    try:
        module = load_scraper(machine_store)
        base_url = str(getattr(module, 'BASE_URL', '') or '').rstrip('/')
        if base_url and not product_url.lower().startswith(base_url.lower() + '/products/'):
            return {'ok': False, 'diagnostic': diagnostic_name, 'error': 'url_not_allowed_for_store',
                    'store': machine_store, 'base_url': base_url, 'url': product_url}

        product_json_method = getattr(module, 'product_json', None)
        make_item_method = getattr(module, 'make_item', None)
        if not callable(product_json_method) or not callable(make_item_method):
            return {'ok': False, 'diagnostic': diagnostic_name,
                    'error': 'scraper_missing_product_json_or_make_item'}

        import requests
        session = requests.Session()
        data = product_json_method(session, product_url)
        if not isinstance(data, dict):
            return {'ok': False, 'diagnostic': diagnostic_name, 'error': 'empty_product_json',
                    'store': machine_store, 'query': query, 'url': product_url}

        variants = data.get('variants') or []
        raw_items = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            item = make_item_method(data, variant, product_url, query)
            if isinstance(item, dict):
                raw_items.append(item)

        inspected = []
        for index, raw_item in enumerate(raw_items):
            prepared = clean_result(raw_item, machine_store)
            if not isinstance(prepared, dict):
                inspected.append({'index': index, 'error': 'clean_result_returned_none',
                                  'raw_keys': sorted(str(k) for k in raw_item.keys())})
                continue

            direct_full = match_snapshot(prepared)
            resolved = _resolve_offer_identity(prepared, query)

            minimal = {
                'store': prepared.get('store') or machine_store,
                'name': prepared.get('name'), 'brand': prepared.get('brand') or '',
                'url': prepared.get('url') or '',
            }
            if prepared.get('size_ml') not in (None, ''):
                minimal['size_ml'] = prepared.get('size_ml')
            minimal_match = match_snapshot(clean_result(minimal, machine_store))

            differential = []
            core_keys = {'store', 'name', 'brand', '_raw_name', '_raw_brand', 'url', 'size_ml'}
            for key in sorted(prepared.keys(), key=str):
                if key in core_keys:
                    continue
                reduced = dict(prepared)
                reduced.pop(key, None)
                differential.append({'removed_key': key, **match_snapshot(reduced)})

            inspected.append({
                'index': index,
                'raw': {
                    'name': raw_item.get('name'), 'brand': raw_item.get('brand'),
                    'url': raw_item.get('url'), 'size_ml': raw_item.get('size_ml'),
                    'source': raw_item.get('source'), 'identity': raw_item.get('identity'),
                    'attributes': raw_item.get('attributes'), 'offer': raw_item.get('offer'),
                    'provenance': raw_item.get('provenance'),
                },
                'clean': compact(prepared),
                'tests': {
                    'direct_full_clean_offer': direct_full,
                    'authoritative_resolve_offer_identity': {
                        'match_status': resolved.get('_match_status') if isinstance(resolved, dict) else None,
                        'catalog_id': resolved.get('catalog_id') if isinstance(resolved, dict) else None,
                        'canonical_name': resolved.get('canonical_name') if isinstance(resolved, dict) else None,
                        'canonical_brand': resolved.get('canonical_brand') if isinstance(resolved, dict) else None,
                        'match_method': resolved.get('match_method') if isinstance(resolved, dict) else None,
                        'match_score': resolved.get('match_score') if isinstance(resolved, dict) else None,
                        'match_error': resolved.get('_match_error') if isinstance(resolved, dict) else None,
                    },
                    'minimal_controlled_shape': minimal_match,
                },
                'top_level_differential': differential,
            })

        return {'ok': True, 'diagnostic': diagnostic_name, 'store': machine_store,
                'query': query, 'url': product_url, 'product_title': data.get('title'),
                'product_vendor': data.get('vendor'), 'variant_count': len(variants),
                'item_count': len(raw_items), 'items': inspected}
    except Exception as exc:
        return {'ok': False, 'diagnostic': diagnostic_name,
                'error': f'{type(exc).__name__}: {exc}', 'store': machine_store,
                'query': query, 'url': product_url}
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass

@app.get('/',include_in_schema=False)
def root():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'app':'ScentHunter','status':'running','architecture':APP_VERSION,'error':'frontend/index.html not found'}

def _runtime_subprocesses():
    """Read-only runtime snapshot of scraper worker subprocesses on Linux."""
    items=[]
    proc_root=Path('/proc')
    if proc_root.exists():
        for entry in proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            pid=int(entry.name)
            if pid == os.getpid():
                continue
            try:
                cmdline=(entry / 'cmdline').read_bytes().replace(b'\\x00',b' ').decode('utf-8','replace').strip()
                if not cmdline:
                    continue
                if "python" not in cmdline.lower():
                    continue
                stat=(entry / 'stat').read_text(errors='replace').split()
                state=stat[2] if len(stat)>2 else None
                items.append({"pid":pid,"state":state,"cmdline":cmdline[:500]})
            except (FileNotFoundError,PermissionError,OSError):
                continue
    return items

def _semaphore_snapshot(semaphore):
    return {
        "available": getattr(semaphore, "_value", None),
        "capacity": None,
    }

@app.get('/diagnostic/runtime')
def diagnostic_runtime():
    """READ-ONLY diagnostic of search jobs, threads, semaphores and workers.

    This endpoint does not start/cancel searches and does not modify runtime state.
    It exists specifically to compare the process immediately after search #1
    with the process while search #2 is stuck.
    """
    now=time.time()
    with JOBS_LOCK:
        jobs=[]
        for job_id,job in JOBS.items():
            jobs.append({
                "job_id":job_id,
                "query":job.get("query"),
                "completed":bool(job.get("completed")),
                "started_at":job.get("started_at"),
                "age_sec":round(now-float(job.get("started_at",now)),3),
                "offer_count":len(job.get("offers",[])),
                "result_count":len(job.get("results",[])),
                "store_count":len(job.get("stores",{})),
                "errors":dict(job.get("errors",{})),
            })

    threads=[]
    for t in threading.enumerate():
        threads.append({
            "name":t.name,
            "alive":t.is_alive(),
            "daemon":t.daemon,
        })

    store_threads=[t for t in threads if t["name"].startswith("scenthunter-store-")]
    search_threads=[t for t in threads if t["name"].startswith("scenthunter-search-")]

    return {
        "diagnostic": "runtime-state-read-only",
        "pid":os.getpid(),
        "timestamp":now,
        "jobs":jobs,
        "job_count":len(jobs),
        "active_jobs":sum(1 for j in jobs if not j["completed"]),
        "threads":threads,
        "thread_count":len(threads),
        "active_store_threads":store_threads,
        "active_search_threads":search_threads,
        "semaphores":{
            "light":{"available":getattr(LIGHT_SEMAPHORE,"_value",None),"capacity":LIGHT_WORKERS},
            "network":{"available":getattr(NETWORK_SEMAPHORE,"_value",None),"capacity":NETWORK_WORKERS},
            "browser":{"available":getattr(BROWSER_SEMAPHORE,"_value",None),"capacity":BROWSER_WORKERS},
        },
        "worker_processes":_runtime_subprocesses(),
    }


# ============================================================================
# DEEP RUNTIME DIAGNOSTIC (READ-ONLY / NO SEARCH BEHAVIOUR CHANGES)
# ============================================================================
from collections import deque

_RUNTIME_DIAG = deque(maxlen=1000)
_RUNTIME_DIAG_LOCK = threading.Lock()
_RUNTIME_DIAG_STARTED = time.time()

def _runtime_diag_event(event, **data):
    item = {
        "ts": round(time.time(), 3),
        "age_sec": round(time.time() - _RUNTIME_DIAG_STARTED, 3),
        "event": str(event),
        **data,
    }
    try:
        with _RUNTIME_DIAG_LOCK:
            _RUNTIME_DIAG.append(item)
    except Exception:
        pass

def _runtime_diag_memory():
    out = {}
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(("VmRSS:", "VmSize:", "Threads:")):
                    k, v = line.split(":", 1)
                    out[k] = v.strip()
    except Exception:
        pass
    return out

def _runtime_diag_stacks():
    frames = sys._current_frames()
    result = []
    for t in threading.enumerate():
        if not (
            t.name.startswith("scenthunter-store-")
            or t.name.startswith("scenthunter-search-")
            or t.name.startswith("AnyIO")
            or t.name.startswith("ThreadPoolExecutor")
        ):
            continue
        item = {
            "name": t.name,
            "ident": t.ident,
            "alive": t.is_alive(),
            "daemon": t.daemon,
        }
        frame = frames.get(t.ident)
        if frame is not None:
            try:
                import traceback as _tb
                item["stack"] = _tb.format_stack(frame)[-18:]
            except Exception as exc:
                item["stack_error"] = f"{type(exc).__name__}: {exc}"
        result.append(item)
    return result

@app.get("/diagnostic/runtime-deep")
def diagnostic_runtime_deep():
    """
    Deep read-only runtime probe.
    Crucially, it NEVER blocks waiting for JOBS_LOCK: it first reports whether
    the lock is currently locked, then tries it only for 50 ms.
    """
    now = time.time()
    lock_locked = False
    jobs_snapshot = None
    lock_acquired = False

    try:
        lock_locked = bool(JOBS_LOCK.locked())
    except Exception:
        lock_locked = None

    try:
        lock_acquired = JOBS_LOCK.acquire(timeout=0.05)
    except Exception:
        lock_acquired = False

    if lock_acquired:
        try:
            jobs_snapshot = []
            for job_id, job in JOBS.items():
                jobs_snapshot.append({
                    "job_id": job_id,
                    "query": job.get("query"),
                    "completed": bool(job.get("completed")),
                    "status": job.get("status"),
                    "age_sec": round(now - float(job.get("started_at", now)), 3),
                    "offer_count": len(job.get("offers", [])),
                    "result_count": len(job.get("results", [])),
                    "store_count": len(job.get("stores", {})),
                    "stores": dict(job.get("stores", {})),
                    "errors": dict(job.get("errors", {})),
                })
        finally:
            JOBS_LOCK.release()

    with _RUNTIME_DIAG_LOCK:
        events = list(_RUNTIME_DIAG)

    return {
        "diagnostic": "runtime-deep-read-only-v1",
        "timestamp": now,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "app_version": APP_VERSION,
        "jobs_lock": {
            "locked_when_checked": lock_locked,
            "acquired_within_50ms": lock_acquired,
        },
        "jobs": jobs_snapshot,
        "job_count": len(jobs_snapshot) if jobs_snapshot is not None else None,
        "active_jobs": (
            sum(1 for j in jobs_snapshot if not j["completed"])
            if jobs_snapshot is not None else None
        ),
        "threads": {
            "total": threading.active_count(),
            "all": [
                {"name": t.name, "ident": t.ident, "alive": t.is_alive(), "daemon": t.daemon}
                for t in threading.enumerate()
            ],
            "stacks": _runtime_diag_stacks(),
        },
        "semaphores": {
            "light": {
                "available": getattr(LIGHT_SEMAPHORE, "_value", None),
                "capacity": LIGHT_WORKERS,
            },
            "network": {
                "available": getattr(NETWORK_SEMAPHORE, "_value", None),
                "capacity": NETWORK_WORKERS,
            },
            "browser": {
                "available": getattr(BROWSER_SEMAPHORE, "_value", None),
                "capacity": BROWSER_WORKERS,
            },
        },
        "worker_processes": _runtime_subprocesses(),
        "memory": _runtime_diag_memory(),
        "events": events[-500:],
    }

@app.get('/health')
def health():
    return {'status':'healthy','architecture':APP_VERSION,'stores':STORES,'lightweight_stores':LIGHTWEIGHT_STORES,'network_heavy_stores':NETWORK_HEAVY_STORES,'browser_stores':BROWSER_STORES,'light_workers':LIGHT_WORKERS,'network_workers':NETWORK_WORKERS,'browser_workers':BROWSER_WORKERS,'store_timeouts':STORE_TIMEOUTS,'job_timeout':JOB_TIMEOUT_SECONDS}

@app.get('/catalog-status')
def catalog_status_endpoint():
    """Read-only catalog/discovery/hydration status for diagnostics."""
    try:
        statuses = catalog_store_status() if callable(catalog_store_status) else {}
    except Exception as exc:
        statuses = {'_error': f'{type(exc).__name__}:{exc}'}
    with _CATALOG_BOOTSTRAP_LOCK:
        return {
            'bootstrap_started': _CATALOG_BOOTSTRAP_STARTED,
            'bootstrap_running': _CATALOG_BOOTSTRAP_RUNNING,
            'bootstrap_done': _CATALOG_BOOTSTRAP_DONE,
            'bootstrap_error': _CATALOG_BOOTSTRAP_ERROR,
            'hydration_started': _CATALOG_HYDRATION_STARTED,
            'stores': statuses,
        }


@app.get('/catalog/hydration-errors')
def catalog_hydration_errors_endpoint(store: str = 'perfumemarket', limit: int = 20):
    """Read-only diagnostic view of recent hydration errors."""
    store_key = str(store or '').strip().lower()
    if store_key not in STORES:
        return {'error': f'unknown_store:{store_key}', 'stores': STORES}
    limit_value = max(1, min(int(limit or 20), 100))
    if not callable(catalog_db):
        return {'store': store_key, 'errors': [], 'error': 'catalog_db_unavailable'}
    conn = catalog_db()
    try:
        rows = conn.execute(
            """SELECT store,url,state,attempts,last_error,last_http_status,
                              last_started_at,last_finished_at,available_at
                       FROM hydration_queue
                       WHERE store=? AND state IN ('ERROR','DEAD')
                       ORDER BY last_finished_at DESC, attempts DESC
                       LIMIT ?""",
            (store_key, limit_value),
        ).fetchall()
        return {
            'store': store_key,
            'count': len(rows),
            'errors': [dict(row) for row in rows],
        }
    finally:
        conn.close()


@app.get('/catalog/hydration-status')
def catalog_hydration_status_endpoint():
    """Detailed persistent hydration queue status, read-only."""
    try:
        statuses = catalog_hydration_status() if callable(catalog_hydration_status) else {}
        return {
            'workers': 8,
            'max_workers_per_store': 2,
            'statuses': statuses,
        }
    except Exception as exc:
        return {
            'workers': 8,
            'max_workers_per_store': 2,
            'statuses': {},
            'error': f'{type(exc).__name__}:{exc}',
        }


@app.get('/search-start')
def search_start(q: str):
    query = str(q or '').strip()
    if not query:
        return {
            'job_id': '',
            'query': '',
            'completed': True,
            'status': 'completed',
            'count': 0,
            'results': [],
            'unresolved_offers': [],
            'identity_scope': [],
            'comparisons': [],
            'errors': {},
            'stores': {},
        }

    # A fresh Fly volume starts empty. Wait for background catalog discovery
    # instead of starting a search that can only return zero results.
    if not _catalog_is_ready():
        with _CATALOG_BOOTSTRAP_LOCK:
            bootstrap_running = _CATALOG_BOOTSTRAP_RUNNING
            bootstrap_error = _CATALOG_BOOTSTRAP_ERROR
        if bootstrap_error and not bootstrap_running:
            return {
                'job_id': '',
                'query': query,
                'completed': True,
                'status': 'error',
                'count': 0,
                'offer_count': 0,
                'results': [],
                'unresolved_offers': [],
                'identity_scope': [],
                'comparisons': [],
                'errors': {'catalog': bootstrap_error},
                'stores': {},
            }
        return {
            'job_id': '',
            'query': query,
            'completed': False,
            'status': 'busy',
            'retry_after_ms': 1500,
            'count': 0,
            'offer_count': 0,
            'results': [],
            'unresolved_offers': [],
            'identity_scope': [],
            'comparisons': [],
            'errors': {'catalog': 'catalog_bootstrapping'},
            'stores': {},
        }

    # Cancellation handshake must never block the HTTP request for a full
    # store/job timeout.  If the previous job is still shutting down, the
    # frontend can retry /search-start after a short delay.
    if not _cancel_active_jobs(wait_timeout=2.5):
        return {
            'job_id': '',
            'query': query,
            'completed': False,
            'status': 'busy',
            'retry_after_ms': 700,
            'count': 0,
            'offer_count': 0,
            'results': [],
            'unresolved_offers': [],
            'identity_scope': [],
            'comparisons': [],
            'errors': {'job': 'previous_search_still_stopping'},
            'stores': {},
        }

    job_id = _new_job(query)
    threading.Thread(
        target=_run_job,
        args=(job_id, query),
        daemon=True,
        name=f'scenthunter-search-{job_id[:8]}'
    ).start()

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
            if _is_non_fragrance_offer(item):
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
                "count": report["count"],
                "elapsed": report["elapsed"],
                "details": dict(report.get("details") or {}),
            }
            for report in reports
        },
    }

@app.get('/frontend')
def frontend():
    if FRONTEND_INDEX.exists(): return FileResponse(FRONTEND_INDEX)
    return {'error':'frontend/index.html not found'}

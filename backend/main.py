from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import uuid
from pathlib import Path

APP_VERSION = '3.1-catalog-identity'
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

STORES = [
    'bplatz', 'deloox', 'parfumcity', 'parfumzentrum',
    'perfumemarket', 'sabina', 'orioudh', 'easycosmetic',
]
STORE_LABELS = {
    'bplatz': 'Bplatz',
    'deloox': 'Deloox',
    'parfumcity': 'ParfumCity',
    'parfumzentrum': 'ParfumZentrum',
    'perfumemarket': 'PerfumeMarket',
    'sabina': 'Sabina',
    'orioudh': 'Orioudh',
    'easycosmetic': 'Easycosmetic',
}
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_INDEX = BASE_DIR.parent / 'frontend' / 'index.html'
PRODUCT_CATALOG_PATH = BASE_DIR / 'product_catalog.json'

LIGHTWEIGHT_STORES = [
    'bplatz', 'parfumcity', 'parfumzentrum',
    'perfumemarket', 'orioudh', 'easycosmetic',
]
NETWORK_HEAVY_STORES = ['deloox']
BROWSER_STORES = ['sabina']
LIGHT_WORKERS = 2
NETWORK_WORKERS = 1
BROWSER_WORKERS = 1
STORE_TIMEOUT_SECONDS = 60.0
STORE_TIMEOUTS = {
    'bplatz': 60.0,
    'deloox': 75.0,
    'parfumcity': 60.0,
    'parfumzentrum': 60.0,
    'perfumemarket': 60.0,
    'sabina': 70.0,
    'orioudh': 60.0,
    'easycosmetic': 60.0,
}
JOB_TIMEOUT_SECONDS = 125.0
LIGHT_SEMAPHORE = threading.Semaphore(LIGHT_WORKERS)
NETWORK_SEMAPHORE = threading.Semaphore(NETWORK_WORKERS)
BROWSER_SEMAPHORE = threading.Semaphore(BROWSER_WORKERS)


def _safe_float(value):
    try:
        if value is None or value == '':
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_store(value, fallback):
    text = str(value or fallback).strip().lower()
    return {
        'bplatz.de': 'bplatz',
        'parfum city': 'parfumcity',
        'parfum zentrum': 'parfumzentrum',
        'parfum-zentrum': 'parfumzentrum',
        'perfume market': 'perfumemarket',
        'orioudh.com': 'orioudh',
    }.get(text, text)


def clean_result(item, store):
    result = dict(item)
    machine_store = _normalise_store(
        result.get('store') or result.get('shop'),
        store,
    )
    result['store'] = STORE_LABELS.get(machine_store, machine_store)
    result['shop'] = STORE_LABELS.get(machine_store, machine_store)

    if 'available' not in result and 'in_stock' in result:
        result['available'] = bool(result.get('in_stock'))

    if result.get('size_ml') in (None, ''):
        for key in ('volume_ml', 'format_ml', 'size'):
            value = result.get(key)
            if value not in (None, ''):
                parsed = _safe_float(value)
                if parsed is not None:
                    result['size_ml'] = parsed
                    break

    if 'price_num' not in result:
        parsed = _safe_float(result.get('price'))
        if parsed is not None:
            result['price_num'] = parsed

    return result


def result_key(item):
    store = _normalise_store(
        item.get('store') or item.get('shop'),
        '',
    )
    url = str(
        item.get('url') or item.get('product_url') or ''
    ).strip().lower()
    product_id = str(
        item.get('store_product_id')
        or item.get('product_id')
        or item.get('sku')
        or ''
    ).strip().lower()
    name = ' '.join(
        str(item.get('name') or item.get('title') or '').split()
    ).lower()
    size = _safe_float(item.get('size_ml'))
    return (
        store,
        url or product_id or name,
        round(size, 3) if size is not None else '',
    )


def dedupe_results(results):
    seen = set()
    output = []
    for item in results:
        key = result_key(item)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def sort_results(results):
    def key(item):
        available = item.get('available')
        price = _safe_float(item.get('price_num'))
        rank = 2 if available is False else 0 if price is not None else 1
        return rank, price if price is not None else 999999.0

    return sorted(results, key=key)


# ============================================================
# GENERIC CATALOG IDENTITY ENGINE
# ============================================================

_IDENTITY_SIZE_RE = re.compile(
    r'\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|g|kg|oz|fl\s*oz)\b',
    re.I,
)
_IDENTITY_CONCENTRATION_RE = re.compile(
    r'\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|'
    r'eau\s+de\s+cologne|eau\s+fraiche|extrait\s+de\s+parfum|'
    r'parfum|perfume|edp|edt|edc|extrait)\b',
    re.I,
)
_IDENTITY_GENERIC_WORDS = {
    'collection', 'fragrance', 'fragrances', 'perfume', 'parfum',
    'spray', 'vaporisateur', 'for', 'him', 'her', 'men', 'women',
    'man', 'woman', 'male', 'female', 'homme', 'femme', 'uomo',
    'donna', 'pour', 'the', 'new', 'edition', 'original',
}


def _identity_norm(value):
    text = str(value or '').strip().lower()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('’', "'").replace('`', "'")
    text = re.sub(r'(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)', ' ', text)
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _identity_tokens(value, *, strip_size=True, strip_concentration=True):
    text = _identity_norm(value)
    if strip_size:
        text = _IDENTITY_SIZE_RE.sub(' ', text)
    if strip_concentration:
        text = _IDENTITY_CONCENTRATION_RE.sub(' ', text)
    return [token for token in text.split() if token]


def _identity_without_brand(value, brand):
    text = _identity_norm(value)
    brand_n = _identity_norm(brand)
    if brand_n:
        text = re.sub(
            rf'\b{re.escape(brand_n)}\b',
            ' ',
            text,
        )
    return re.sub(r'\s+', ' ', text).strip()


def _identity_concentration(value):
    text = _identity_norm(value)
    if re.search(r'\bextrait(?:\s+de)?\s+parfum\b|\bextrait\b', text):
        return 'extrait de parfum'
    if re.search(r'\beau\s+de\s+parfum\b|\bedp\b', text):
        return 'eau de parfum'
    if re.search(r'\beau\s+de\s+toilette\b|\bedt\b', text):
        return 'eau de toilette'
    if re.search(r'\beau\s+de\s+cologne\b|\bedc\b', text):
        return 'eau de cologne'
    if re.search(r'\bparfum\b|\bperfume\b', text):
        return 'parfum'
    return ''


def _identity_gender(value):
    text = _identity_norm(value)
    female = bool(re.search(
        r'\b(?:for\s+her|for\s+women|women|woman|female|'
        r'femme|femmes|donna|donne|dames|vrouwen)\b',
        text,
    ))
    male = bool(re.search(
        r'\b(?:for\s+him|for\s+men|men|man|male|'
        r'homme|hommes|uomo|uomini|heren|mannen)\b',
        text,
    ))
    if female and not male:
        return 'Donna'
    if male and not female:
        return 'Uomo'
    if re.search(r'\b(?:unisex|mixte|unisexe)\b', text):
        return 'Unisex'
    return ''


class CatalogIdentityEngine:
    """
    Generic product identity resolver.

    It does not contain perfume/store-specific rules. The only authority is
    product_catalog.json. A retailer title is mapped to the most specific
    catalog identity whose canonical name/alias is represented in that title.
    Bottle size is deliberately excluded from identity, while concentration
    and explicit gender are used only to disambiguate otherwise equal names.
    """

    def __init__(self, path):
        self.records = []
        self.exact = {}
        self.by_brand = {}
        self._load(path)

    def _load(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
        except Exception as exc:
            print(
                f'CATALOG_IDENTITY_LOAD_ERROR: {type(exc).__name__}: {exc}',
                flush=True,
            )
            return

        products = payload.get('products', []) if isinstance(payload, dict) else []
        variants = payload.get('variants', []) if isinstance(payload, dict) else []
        if not isinstance(products, list):
            products = []
        if not isinstance(variants, list):
            variants = []

        merged = {}
        for product in products:
            if not isinstance(product, dict):
                continue
            product_id = str(product.get('product_id') or product.get('id') or '').strip()
            if not product_id:
                continue
            merged[product_id] = {
                'product_id': product_id,
                'brand': str(
                    product.get('brand_name')
                    or product.get('brand')
                    or ''
                ).strip(),
                'canonical_name': str(
                    product.get('canonical_name')
                    or product.get('name')
                    or ''
                ).strip(),
                'family_name': str(product.get('family_name') or '').strip(),
                'concentration': str(product.get('concentration') or '').strip(),
                'gender': str(product.get('gender') or '').strip(),
                'aliases': [
                    str(value).strip()
                    for value in (product.get('aliases') or [])
                    if str(value).strip()
                ],
            }

        for variant in variants:
            if not isinstance(variant, dict):
                continue
            product_id = str(variant.get('product_id') or '').strip()
            target = merged.get(product_id)
            if target is None:
                continue
            for value in variant.get('aliases') or []:
                value = str(value).strip()
                if value and value not in target['aliases']:
                    target['aliases'].append(value)

        for item in merged.values():
            if not item['canonical_name'] or not item['brand']:
                continue

            aliases = list(item['aliases'])
            aliases.append(item['canonical_name'])
            alias_data = []
            for alias in aliases:
                alias_no_brand = _identity_without_brand(alias, item['brand'])
                tokens = _identity_tokens(alias_no_brand)
                if not tokens:
                    continue
                alias_n = ' '.join(tokens)
                alias_data.append((alias_n, tuple(tokens)))
                self.exact.setdefault(
                    (self._brand_key(item['brand']), alias_n),
                    [],
                ).append(item)

            item['_aliases'] = list(dict.fromkeys(alias_data))
            item['_brand_key'] = self._brand_key(item['brand'])
            item['_canonical_tokens'] = tuple(
                _identity_tokens(
                    _identity_without_brand(
                        item['canonical_name'],
                        item['brand'],
                    )
                )
            )
            self.records.append(item)
            self.by_brand.setdefault(item['_brand_key'], []).append(item)

        print(
            f'CATALOG_IDENTITY_READY records={len(self.records)} aliases={sum(len(x["_aliases"]) for x in self.records)}',
            flush=True,
        )

    @staticmethod
    def _brand_key(value):
        return _identity_norm(value)

    def _candidate_score(self, item, raw_name, raw_text):
        brand = item['brand']
        raw_no_brand = _identity_without_brand(raw_text, brand)
        raw_tokens = _identity_tokens(raw_no_brand)
        raw_set = set(raw_tokens)
        if not raw_set:
            return None

        raw_concentration = _identity_concentration(raw_name)
        raw_gender = _identity_gender(raw_name)
        catalog_concentration = _identity_concentration(item.get('concentration', ''))
        catalog_gender = _identity_gender(item.get('gender', ''))
        if not catalog_gender:
            catalog_gender = _identity_gender(item.get('canonical_name', ''))

        best = None
        canonical_len = len(item['_canonical_tokens'])

        for alias_n, alias_tokens in item['_aliases']:
            alias_set = set(alias_tokens)
            if not alias_set.issubset(raw_set):
                continue

            exact = alias_n == ' '.join(raw_tokens)
            canonical_n = ' '.join(item['_canonical_tokens'])
            canonical_exact = alias_n == canonical_n
            overlap = len(alias_set)
            extra = len(raw_set - alias_set)

            score = (
                100000 if exact else 0,
                10000 if exact and canonical_exact else 0,
                overlap * 1000,
                canonical_len * 100,
                500 if raw_concentration and catalog_concentration == raw_concentration else 0,
                250 if raw_gender and catalog_gender == raw_gender else 0,
                -extra,
                len(alias_n),
            )
            if best is None or score > best:
                best = score

        return best

    def resolve(self, product):
        if not isinstance(product, dict) or not self.records:
            return product

        raw_name = str(
            product.get('name')
            or product.get('title')
            or product.get('product_name')
            or ''
        ).strip()
        if not raw_name:
            return product

        raw_brand = str(
            product.get('brand')
            or product.get('source_brand')
            or ''
        ).strip()
        raw_text = ' '.join(
            value for value in (
                raw_name,
                str(product.get('title') or ''),
                str(product.get('product_name') or ''),
            ) if value
        )

        brand_key = self._brand_key(raw_brand)
        pool = self.by_brand.get(brand_key) if brand_key else None
        if not pool:
            pool = self.records

        raw_no_brand = _identity_without_brand(raw_text, raw_brand)
        raw_tokens = _identity_tokens(raw_no_brand)
        if not raw_tokens:
            return product
        raw_alias_n = ' '.join(raw_tokens)

        exact_candidates = []
        if brand_key:
            exact_candidates.extend(
                self.exact.get((brand_key, raw_alias_n), [])
            )
        if not exact_candidates:
            for item in pool:
                for alias_n, _ in item['_aliases']:
                    if alias_n == raw_alias_n:
                        exact_candidates.append(item)
                        break

        candidates = exact_candidates or pool
        best_item = None
        best_score = None
        for item in candidates:
            score = self._candidate_score(item, raw_name, raw_text)
            if score is None:
                continue
            if best_score is None or score > best_score:
                best_item = item
                best_score = score

        if best_item is None:
            return product

        result = dict(product)
        result['source_name'] = raw_name
        result['source_brand'] = raw_brand or best_item['brand']
        result['brand'] = best_item['brand']
        result['canonical_brand'] = best_item['brand']
        result['canonical_name'] = best_item['canonical_name']
        result['catalog_variant'] = best_item['canonical_name']
        result['catalog_product_id'] = best_item['product_id']
        result['family_name'] = best_item.get('family_name') or best_item['canonical_name']
        if best_item.get('concentration'):
            result['canonical_concentration'] = best_item['concentration']
            if not result.get('concentration'):
                result['concentration'] = best_item['concentration']
        if best_item.get('gender'):
            result['canonical_gender'] = best_item['gender']
            if not result.get('gender'):
                result['gender'] = best_item['gender']
        result['identity_match'] = 'catalog_alias'
        result['name'] = best_item['canonical_name']
        result['title'] = best_item['canonical_name']
        return result

    def key(self, product):
        canonical_id = str(product.get('catalog_product_id') or '').strip()
        if canonical_id:
            # The catalog can contain historical duplicate rows for the same
            # canonical perfume. Name/concentration/gender makes the identity
            # stable across those rows and across catalog migrations.
            brand = _identity_norm(
                product.get('canonical_brand')
                or product.get('brand')
                or ''
            )
            name = _identity_norm(
                product.get('canonical_name')
                or product.get('name')
                or ''
            )
            concentration = _identity_norm(
                product.get('canonical_concentration')
                or product.get('concentration')
                or ''
            )
            gender = _identity_norm(
                product.get('canonical_gender')
                or product.get('gender')
                or ''
            )
            return ('catalog', brand, name, concentration, gender)

        return None


CATALOG_IDENTITY = CatalogIdentityEngine(PRODUCT_CATALOG_PATH)


def _identity_resolve(product):
    try:
        return CATALOG_IDENTITY.resolve(product)
    except Exception as exc:
        print(
            f'CATALOG_IDENTITY_RUNTIME_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return product


def _identity_key(product):
    key = CATALOG_IDENTITY.key(product)
    if key is not None:
        return key

    store = _normalise_store(
        product.get('store') or product.get('shop'),
        '',
    )
    url = str(
        product.get('url') or product.get('product_url') or ''
    ).strip().lower()
    return (
        'raw',
        store,
        url,
        _identity_norm(
            product.get('name')
            or product.get('title')
            or product.get('product_name')
            or ''
        ),
    )


def _is_better_offer(candidate, current):
    candidate_available = candidate.get('available') is not False
    current_available = current.get('available') is not False
    if candidate_available != current_available:
        return candidate_available

    candidate_price = _safe_float(candidate.get('price_num'))
    current_price = _safe_float(current.get('price_num'))
    if candidate_price is not None and current_price is None:
        return True
    if candidate_price is None and current_price is not None:
        return False
    if candidate_price is not None and current_price is not None:
        if candidate_price != current_price:
            return candidate_price < current_price

    return str(candidate.get('store', '')).lower() < str(current.get('store', '')).lower()


def collapse_identity_results(results):
    """One card per canonical perfume identity, never one card per retailer."""
    grouped = {}
    for raw in results:
        item = _identity_resolve(clean_result(raw, raw.get('store') or raw.get('shop') or ''))
        key = _identity_key(item)
        current = grouped.get(key)
        if current is None:
            grouped[key] = item
        elif _is_better_offer(item, current):
            replacement = dict(item)
            replacement['offers_count'] = int(current.get('offers_count') or 1) + 1
            grouped[key] = replacement
        else:
            current['offers_count'] = int(current.get('offers_count') or 1) + 1

    output = list(grouped.values())
    return sort_results(dedupe_results(output))


# ============================================================
# STORE EXECUTION
# ============================================================

def _empty_report(store, status='error', elapsed=0.0, error=None):
    return {
        'store': store,
        'status': status,
        'elapsed': round(elapsed, 3),
        'count': 0,
        'results': [],
        'error': error,
    }


def load_scraper(store):
    return importlib.import_module(f'scrapers.{store}.scraper')


def run_store(store, query):
    started = time.monotonic()
    try:
        search = getattr(load_scraper(store), 'search', None)
        if not callable(search):
            raise RuntimeError(f'scraper {store} non espone search(query)')

        raw = search(query)
        if store == 'parfumzentrum' and not raw:
            time.sleep(.25)
            raw = search(query)

        rows = (
            [] if raw is None
            else list(raw) if not isinstance(raw, list)
            else raw
        )
        cleaned = [
            clean_result(x, store)
            for x in rows
            if isinstance(x, dict)
        ]
        return {
            'store': store,
            'status': 'ok' if cleaned else 'empty',
            'elapsed': round(time.monotonic() - started, 3),
            'count': len(cleaned),
            'results': cleaned,
            'error': None,
        }
    except Exception as exc:
        traceback.print_exc()
        return {
            'store': store,
            'status': 'error',
            'error': str(exc),
            'error_code': 'runtime_error',
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'results': [],
        }


WORKER_CODE = r'''
import importlib, json, sys
store = sys.argv[1]
query = sys.argv[2]

def emit(event, **payload):
    print(
        json.dumps(
            {'event': event, **payload},
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )

try:
    module = importlib.import_module(f'scrapers.{store}.scraper')
    stream = getattr(module, 'search_stream', None)
    if callable(stream):
        rows = []
        def on_result(row):
            if isinstance(row, dict):
                rows.append(row)
                emit('result', row=row)
        returned = stream(query, on_result)
        if returned is not None:
            try:
                for row in returned:
                    if isinstance(row, dict):
                        emit('result', row=row)
                        rows.append(row)
            except TypeError:
                pass
        emit('done', count=len(rows), streaming=True)
    else:
        search = getattr(module, 'search', None)
        if not callable(search):
            raise RuntimeError(
                f'scraper {store} non espone search(query)'
            )
        raw = search(query)
        if raw is None:
            rows = []
        elif isinstance(raw, list):
            rows = raw
        elif isinstance(raw, tuple):
            rows = list(raw)
        else:
            try:
                rows = list(raw)
            except TypeError:
                rows = []
        for row in rows:
            if isinstance(row, dict):
                emit('result', row=row)
        emit('done', count=len(rows), streaming=False)
except BaseException as exc:
    emit('error', error=f'{type(exc).__name__}: {exc}')
    raise SystemExit(1)
'''


def _kill_process_tree(process):
    try:
        if process.poll() is not None:
            return
        if os.name != 'nt':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _run_store_subprocess(store, query, on_result=None):
    started = time.monotonic()
    timeout = STORE_TIMEOUTS.get(store, STORE_TIMEOUT_SECONDS)
    env = os.environ.copy()
    current = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = str(BASE_DIR) + (
        os.pathsep + current if current else ''
    )
    process = None
    rows = []
    worker_error = None

    try:
        process = subprocess.Popen(
            [sys.executable, '-u', '-c', WORKER_CODE, store, query],
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            start_new_session=(os.name != 'nt'),
        )
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args, timeout)
            line = (
                process.stdout.readline()
                if process.stdout is not None
                else ''
            )
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.01)
                continue

            try:
                event = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            kind = event.get('event')
            if kind == 'result' and isinstance(event.get('row'), dict):
                row = clean_result(event['row'], store)
                rows.append(row)
                if callable(on_result):
                    on_result(row)
            elif kind == 'error':
                worker_error = str(
                    event.get('error') or 'worker_error'
                )

        rc = process.wait(timeout=1)
        elapsed = round(time.monotonic() - started, 3)
        if rc != 0 or worker_error:
            return {
                'store': store,
                'status': 'error',
                'elapsed': elapsed,
                'count': len(rows),
                'results': rows,
                'error': worker_error or f'worker_exit_{rc}',
            }
        return {
            'store': store,
            'status': 'ok' if rows else 'empty',
            'elapsed': elapsed,
            'count': len(rows),
            'results': rows,
            'error': None,
        }
    except subprocess.TimeoutExpired:
        if process is not None:
            _kill_process_tree(process)
            try:
                process.communicate(timeout=2)
            except Exception:
                pass
        return _empty_report(
            store,
            elapsed=round(time.monotonic() - started, 3),
            error=f'store_timeout_{timeout:.0f}s',
        )
    except Exception as exc:
        if process is not None:
            _kill_process_tree(process)
            try:
                process.communicate(timeout=1)
            except Exception:
                pass
        return _empty_report(
            store,
            elapsed=round(time.monotonic() - started, 3),
            error=f'{type(exc).__name__}: {exc}',
        )


def _run_controlled_store(store, query, on_report, on_result=None):
    print(
        f'STORE START store={store} query={query!r}',
        flush=True,
    )
    semaphore = LIGHT_SEMAPHORE
    lane = 'light'
    if store in BROWSER_STORES:
        semaphore = BROWSER_SEMAPHORE
        lane = 'browser'
    elif store in NETWORK_HEAVY_STORES:
        semaphore = NETWORK_SEMAPHORE
        lane = 'network'

    wait = time.monotonic()
    if semaphore is not None:
        if not semaphore.acquire(timeout=JOB_TIMEOUT_SECONDS):
            report = _empty_report(
                store,
                error=f'{lane}_lane_unavailable',
            )
            on_report(report)
            return
        waited = round(time.monotonic() - wait, 3)
        if waited > .1:
            print(
                f'STORE QUEUED store={store} lane={lane} waited={waited}',
                flush=True,
            )

    try:
        report = _run_store_subprocess(
            store,
            query,
            on_result=on_result,
        )
    finally:
        if semaphore is not None:
            semaphore.release()

    if report.get('status') == 'error':
        print(
            f"STORE ERROR store={store} error={report.get('error')}",
            flush=True,
        )
    print(
        f"STORE END store={store} status={report.get('status')} "
        f"elapsed={report.get('elapsed')} count={report.get('count')}",
        flush=True,
    )
    on_report(report)


def collect_store_reports_isolated(
    query,
    stores,
    on_report=None,
    on_result=None,
):
    requested = list(stores)
    reports = {}
    lock = threading.Lock()
    threads = []

    def publish(report):
        with lock:
            reports[report['store']] = report
        if callable(on_report):
            on_report(report)

    for store in requested:
        thread = threading.Thread(
            target=_run_controlled_store,
            args=(store, query, publish, on_result),
            daemon=True,
            name=f'scenthunter-store-{store}',
        )
        thread.start()
        threads.append(thread)

    deadline = time.monotonic() + JOB_TIMEOUT_SECONDS
    for thread in threads:
        thread.join(
            timeout=max(0.0, deadline - time.monotonic())
        )

    unfinished = [
        thread.name.rsplit('scenthunter-store-', 1)[-1]
        for thread in threads
        if thread.is_alive()
    ]
    if unfinished:
        print(
            f'SEARCH SUPERVISORS STILL RUNNING stores={unfinished}',
            flush=True,
        )
        with lock:
            for store in unfinished:
                reports.setdefault(
                    store,
                    _empty_report(
                        store,
                        elapsed=JOB_TIMEOUT_SECONDS,
                        error='job_timeout',
                    ),
                )

    return [
        reports[store]
        for store in requested
        if store in reports
    ]


# ============================================================
# SEARCH JOBS / STREAMING
# ============================================================

JOBS = {}
JOBS_LOCK = threading.Lock()


def _new_job(query):
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            'job_id': job_id,
            'query': query,
            'started_at': time.time(),
            'completed': False,
            'results': [],
            'comparisons': [],
            'errors': {},
            'stores': {},
        }
    return job_id


def _snapshot(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return {
                'job_id': job_id,
                'query': '',
                'completed': True,
                'status': 'completed',
                'count': 0,
                'results': [],
                'comparisons': [],
                'errors': {'job': 'job_not_found'},
                'stores': {},
            }

        # Rebuild identities at read time as a final safety net. This also
        # guarantees that a progressive stream cannot leave duplicate cards
        # after late retailer results arrive.
        results = collapse_identity_results(
            list(job['results'])
        )
        job['results'] = results
        return {
            'job_id': job['job_id'],
            'query': job['query'],
            'completed': job['completed'],
            'status': 'completed' if job['completed'] else 'searching',
            'count': len(results),
            'results': list(results),
            'comparisons': list(job['comparisons']),
            'errors': dict(job['errors']),
            'stores': dict(job['stores']),
        }


def _publish_result(job_id, row):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get('completed'):
            return

        clean = clean_result(
            row,
            row.get('store') or row.get('shop') or '',
        )
        clean = _identity_resolve(clean)
        job['results'].append(clean)
        job['results'] = collapse_identity_results(job['results'])
        total = len(job['results'])

    print(
        f"SEARCH PUBLISH RESULT job={job_id} "
        f"store={clean.get('store')} total={total}",
        flush=True,
    )


def _publish_store(job_id, report):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get('completed'):
            return

        store = report['store']
        job['stores'][store] = {
            'status': report.get('status'),
            'elapsed': report.get('elapsed'),
            'count': report.get('count', 0),
        }
        if report.get('error'):
            job['errors'][store] = report['error']

        # Streaming rows have already been published through on_result. Do
        # not append them again here; otherwise the same offer would count
        # twice when the store completion event arrives.
        job['results'] = collapse_identity_results(job['results'])
        total = len(job['results'])

    print(
        f"SEARCH PUBLISH job={job_id} store={store} "
        f"count={report.get('count')} total={total}",
        flush=True,
    )


def _run_job(job_id, query):
    started = time.monotonic()
    print(
        f'SEARCH START job={job_id} query={query!r}',
        flush=True,
    )

    collect_store_reports_isolated(
        query,
        STORES,
        on_report=lambda report: _publish_store(job_id, report),
        on_result=lambda row: _publish_result(job_id, row),
    )

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job['results'] = collapse_identity_results(job['results'])
            job['completed'] = True
            job['elapsed'] = round(
                time.monotonic() - started,
                3,
            )
            elapsed = job['elapsed']
            total = len(job['results'])
        else:
            elapsed = round(
                time.monotonic() - started,
                3,
            )
            total = 0

    print(
        f'SEARCH END job={job_id} elapsed={elapsed} total={total}',
        flush=True,
    )


# ============================================================
# HTTP API
# ============================================================

@app.get('/', include_in_schema=False)
def root():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(
            status_code=500,
            detail='frontend/index.html non trovato',
        )
    return FileResponse(FRONTEND_INDEX)


@app.get('/health')
def health():
    return {
        'status': 'healthy',
        'architecture': APP_VERSION,
        'stores': STORES,
        'lightweight_stores': LIGHTWEIGHT_STORES,
        'network_heavy_stores': NETWORK_HEAVY_STORES,
        'browser_stores': BROWSER_STORES,
        'light_workers': LIGHT_WORKERS,
        'network_workers': NETWORK_WORKERS,
        'browser_workers': BROWSER_WORKERS,
        'store_timeouts': STORE_TIMEOUTS,
        'job_timeout': JOB_TIMEOUT_SECONDS,
        'catalog_identity_records': len(CATALOG_IDENTITY.records),
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
            'comparisons': [],
            'errors': {},
            'stores': {},
        }

    job_id = _new_job(query)
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, query),
        daemon=True,
        name=f'scenthunter-job-{job_id}',
    )
    thread.start()

    return {
        'job_id': job_id,
        'query': query,
        'completed': False,
        'status': 'searching',
        'count': 0,
        'results': [],
        'comparisons': [],
        'errors': {},
        'stores': {},
    }


@app.get('/search-status/{job_id}')
def search_status_path(job_id: str):
    return _snapshot(job_id)


@app.get('/search-status')
def search_status_query(job_id: str):
    return _snapshot(job_id)


@app.get('/search')
def search_perfume(q: str):
    query = str(q or '').strip()
    if not query:
        return {
            'query': '',
            'count': 0,
            'results': [],
            'comparisons': [],
            'errors': {},
            'stores': {},
        }

    job_id = _new_job(query)
    _run_job(job_id, query)
    return _snapshot(job_id)


@app.get('/test-store')
def test_store(store: str, q: str):
    store = str(store or '').strip().lower()
    query = str(q or '').strip()
    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=(
                'Store non valido. Disponibili: '
                + ', '.join(STORES)
            ),
        )
    if not query:
        raise HTTPException(
            status_code=400,
            detail='Parametro q mancante',
        )

    try:
        report = run_store(store, query)
        results = collapse_identity_results(report.get('results', []))
        return {
            'store': store,
            'query': query,
            'count': len(results),
            'results': results,
            'raw_count': report.get('count', 0),
            'status': report.get('status'),
            'error': report.get('error'),
        }
    except Exception as exc:
        traceback.print_exc()
        return {
            'store': store,
            'query': query,
            'count': 0,
            'results': [],
            'error': f'{type(exc).__name__}: {exc}',
        }


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
        if not isinstance(payload, (dict, list)):
            print('PRODUCT_MATCHER: invalid catalog payload; identity matching disabled', flush=True)
            return None
        products = payload.get('products') if isinstance(payload, dict) else payload
        if not products:
            print('PRODUCT_MATCHER: catalog empty; identity matching disabled', flush=True)
            return None
        # Pass the complete catalog payload. No product/variant names are
        # duplicated in application code.
        return ProductMatcher(catalog=payload)
    except Exception as exc:
        print(f'PRODUCT_MATCHER_INIT_ERROR: {type(exc).__name__}: {exc}', flush=True)
        return None

PRODUCT_MATCHER = _load_product_matcher()

class CatalogIdentityResolver:
    """
    Generic catalog-driven identity resolver.
    The catalog is the only source of product/variant knowledge.
    This class contains matching logic only; it never contains perfume names,
    aliases, or variant lists.
    """
    COMMERCIAL_NOISE = {
        'refill', 'refillable', 'refilled',
        'nachfullbar', 'nachfullung', 'nachfullen',
        'nachfuellbar', 'nachfuellung', 'nachfuellen',
        'rechargeable', 'recharge', 'wiederbefullbar',
        'wiederbefuellbar', 'new', 'neu',
    }

    def __init__(self, matcher):
        self.matcher = matcher
        self.catalog = list(getattr(matcher, 'catalog', []) or [])
        self._brands = sorted(
            {
                self._norm(getattr(product, 'brand', ''))
                for product in self.catalog
                if self._norm(getattr(product, 'brand', ''))
            },
            key=lambda value: (-len(value.split()), -len(value)),
        )

    @staticmethod
    def _norm(value):
        text = str(value or '').strip().lower()
        text = re.sub(r'[^a-z0-9]+', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    @classmethod
    def _tokens(cls, value, remove_noise=False):
        tokens = cls._norm(value).split()
        if remove_noise:
            tokens = [token for token in tokens if token not in cls.COMMERCIAL_NOISE]
        return tokens

    @classmethod
    def _remove_size(cls, value):
        text = cls._norm(value)
        text = re.sub(r'\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    @classmethod
    def _strict_tokens(cls, value):
        # Keep concentration words: Parfum/Elixir/Intense can be variant identity.
        return cls._tokens(cls._remove_size(value), remove_noise=True)

    @classmethod
    def _relaxed_tokens(cls, value):
        # Only a fallback for retailer-added concentration descriptors.
        text = cls._remove_size(value)
        text = re.sub(
            r'\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|'
            r'eau\s+de\s+cologne|eau\s+fraiche|'
            r'extrait\s+de\s+parfum|edp|edt|edc|perfume|spray)\b',
            ' ',
            text,
            flags=re.I,
        )
        return cls._tokens(text, remove_noise=True)

    @staticmethod
    def _contains_sequence(container, sequence):
        if not sequence or len(sequence) > len(container):
            return False
        for index in range(len(container) - len(sequence) + 1):
            if container[index:index + len(sequence)] == sequence:
                return True
        return False

    @staticmethod
    def _contains_subsequence(container, sequence):
        if not sequence:
            return True
        position = 0
        for token in container:
            if token == sequence[position]:
                position += 1
                if position == len(sequence):
                    return True
        return False

    @staticmethod
    def _f_score(left, right):
        left_set = set(left)
        right_set = set(right)
        if not left_set or not right_set:
            return 0.0
        intersection = len(left_set & right_set)
        precision = intersection / len(left_set)
        recall = intersection / len(right_set)
        if precision + recall == 0:
            return 0.0
        return 2.0 * precision * recall / (precision + recall)

    @classmethod
    def _variant_score(cls, offer_tokens, candidate_tokens):
        if not offer_tokens or not candidate_tokens:
            return 0.0
        if offer_tokens == candidate_tokens:
            return 1.0

        # Handles retailer omission of duplicated brand/product tokens:
        # "Hugo Boss - Bottled Beyond" vs "Hugo Boss - Boss Bottled Beyond".
        if cls._contains_sequence(candidate_tokens, offer_tokens):
            extra = max(0, len(candidate_tokens) - len(offer_tokens))
            return max(0.82, 0.96 - 0.02 * extra)

        if cls._contains_subsequence(candidate_tokens, offer_tokens):
            extra = max(0, len(candidate_tokens) - len(offer_tokens))
            return max(0.80, 0.91 - 0.02 * extra)

        f_score = cls._f_score(offer_tokens, candidate_tokens)
        return 0.55 + 0.35 * f_score if f_score > 0 else 0.0

    @classmethod
    def _brand_in_query(cls, query, brands):
        query_tokens = cls._tokens(query)
        query_set = set(query_tokens)
        for brand in brands:
            brand_tokens = brand.split()
            if brand_tokens and set(brand_tokens).issubset(query_set):
                return brand
        return ''

    @staticmethod
    def _remove_brand_tokens(tokens, brand):
        if not brand:
            return list(tokens)
        remaining = list(tokens)
        for token in brand.split():
            try:
                remaining.remove(token)
            except ValueError:
                pass
        return remaining

    @staticmethod
    def _product_forms(product):
        values = [
            getattr(product, 'name', ''),
            getattr(product, 'family_name', ''),
        ]
        values.extend(getattr(product, 'aliases', ()) or ())
        return [value for value in values if str(value or '').strip()]

    def _query_scope(self, query):
        query_tokens = self._strict_tokens(query)
        if not query_tokens:
            return list(self.catalog)

        query_brand = self._brand_in_query(query, self._brands)
        query_core = self._remove_brand_tokens(query_tokens, query_brand)

        scoped = []
        for product in self.catalog:
            product_brand = self._norm(getattr(product, 'brand', ''))
            if query_brand and product_brand != query_brand:
                continue

            for form in self._product_forms(product):
                form_tokens = self._strict_tokens(form)
                form_brand = self._norm(getattr(product, 'brand', ''))
                form_core = self._remove_brand_tokens(form_tokens, form_brand)

                if not query_core or set(query_core).issubset(set(form_core)):
                    scoped.append(product)
                    break

                if self._f_score(query_core, form_core) >= 0.62:
                    scoped.append(product)
                    break

        return scoped

    def _best_product(self, offer, query):
        raw_name = str(
            offer.get('name') or offer.get('title') or offer.get('product_name') or ''
        ).strip()
        raw_brand = str(
            offer.get('brand') or offer.get('manufacturer') or ''
        ).strip()
        if not raw_name:
            return None, 'none', 0.0

        scope = self._query_scope(query)
        if not scope:
            return None, 'none', 0.0

        # Hard identifiers are trusted only when the identified catalog product
        # is inside the query scope. This prevents a stale retailer ID from
        # overriding the user's actual search family.
        for key_group, method, score in (
            (('gtin', 'ean', 'ean13', 'ean_code', 'barcode', 'upc'), 'gtin', 1.0),
            (('mpn', 'manufacturer_part_number', 'manufacturerNumber'), 'mpn', 0.99),
            (('catalog_id', 'master_id', 'item_group_id', 'product_id'), 'catalog_id', 0.98),
        ):
            value = str(next((offer.get(key) for key in key_group if offer.get(key)), '') or '').strip().lower()
            if not value:
                continue
            normalized = re.sub(r'[^a-z0-9]+', '', value)
            if not normalized:
                continue
            if method == 'catalog_id':
                product = None
                for candidate in scope:
                    candidate_id = str(getattr(candidate, 'catalog_id', '') or '').strip().lower()
                    if re.sub(r'[^a-z0-9]+', '', candidate_id) == normalized:
                        product = candidate
                        break
                if product is not None:
                    return product, method, score
            else:
                index = getattr(self.matcher, '_by_gtin' if method == 'gtin' else '_by_mpn', {})
                products = index.get(normalized, [])
                for product in products:
                    if product in scope:
                        return product, method, score

        offer_brand = self._norm(raw_brand)
        if not offer_brand:
            source = offer.get('source')
            if isinstance(source, dict):
                offer_brand = self._norm(
                    source.get('source_brand') or source.get('brand') or ''
                )

        offer_forms = [
            raw_name,
            str(offer.get('title') or ''),
            str(offer.get('product_name') or ''),
        ]
        source = offer.get('source')
        if isinstance(source, dict):
            offer_forms.extend([
                str(source.get('source_name') or ''),
                str(source.get('name') or ''),
                str(source.get('title') or ''),
            ])

        best = None
        best_score = 0.0
        best_exactness = -1.0

        for product in scope:
            product_brand = self._norm(getattr(product, 'brand', ''))
            if offer_brand and product_brand and offer_brand != product_brand:
                continue

            candidate_forms = self._product_forms(product)
            strict_best = 0.0
            relaxed_best = 0.0

            for candidate in candidate_forms:
                candidate_tokens = self._strict_tokens(candidate)
                relaxed_candidate_tokens = self._relaxed_tokens(candidate)

                for offer_form in offer_forms:
                    if not offer_form.strip():
                        continue
                    offer_tokens = self._strict_tokens(offer_form)
                    strict_best = max(
                        strict_best,
                        self._variant_score(offer_tokens, candidate_tokens),
                    )
                    relaxed_offer_tokens = self._relaxed_tokens(offer_form)
                    relaxed_best = max(
                        relaxed_best,
                        self._variant_score(
                            relaxed_offer_tokens,
                            relaxed_candidate_tokens,
                        ),
                    )

            score = strict_best
            method = 'catalog_variant'
            if score < 0.82:
                score = relaxed_best
                method = 'catalog_variant_relaxed'

            if score <= 0:
                continue

            candidate_length = min(
                (
                    len(self._strict_tokens(candidate))
                    for candidate in candidate_forms
                    if self._strict_tokens(candidate)
                ),
                default=999,
            )
            exactness = score - (candidate_length * 0.0005)

            if score > best_score or (
                abs(score - best_score) < 0.0001
                and exactness > best_exactness
            ):
                best = product
                best_score = score
                best_exactness = exactness
                best_method = method

        if best is None or best_score < 0.80:
            return None, 'none', best_score
        return best, best_method, best_score

    @staticmethod
    def _safe_size(item):
        explicit = item.get('size_ml')
        if explicit not in (None, ''):
            try:
                return float(str(explicit).replace(',', '.'))
            except (TypeError, ValueError):
                pass
        text = ' '.join(
            str(item.get(key) or '')
            for key in ('name', 'title', 'product_name', 'size', 'format')
        )
        match = re.search(r'\b(\d+(?:[.,]\d+)?)\s*(ml|cl)\b', text, re.I)
        if not match:
            return None
        value = float(match.group(1).replace(',', '.'))
        if match.group(2).lower() == 'cl':
            value *= 10
        return value

    def match(self, offer, query):
        if not isinstance(offer, dict):
            return None

        if self.matcher is not None:
            try:
                if self.matcher._is_non_fragrance_offer(offer):
                    return None
            except Exception:
                pass

        product, method, score = self._best_product(offer, query)
        if product is None:
            return None

        result = dict(offer)
        canonical_name = str(getattr(product, 'name', '') or '').strip()
        canonical_brand = str(getattr(product, 'brand', '') or '').strip()
        if not canonical_name:
            return None

        result.update({
            'catalog_id': getattr(product, 'catalog_id', '') or '',
            'family_id': getattr(product, 'family_id', '') or '',
            'family_name': getattr(product, 'family_name', '') or canonical_name,
            'canonical_name': canonical_name,
            'canonical_brand': canonical_brand,
            'catalog_variant': canonical_name,
            'match_method': method,
            'match_score': round(score, 4),
            'product_identity': getattr(product, 'catalog_id', '') or '',
        })

        resolved_size = self._safe_size(result)
        if resolved_size is not None:
            result['size_ml'] = resolved_size
            catalog_id = getattr(product, 'catalog_id', '') or ''
            result['variant_id'] = f'{catalog_id}:{resolved_size:g}'
        else:
            result['variant_id'] = getattr(product, 'catalog_id', '') or ''

        return result

CATALOG_IDENTITY_RESOLVER = (
    CatalogIdentityResolver(PRODUCT_MATCHER)
    if PRODUCT_MATCHER is not None
    else None
)

def _apply_product_identity(result, query=''):
    # Central catalog-driven identity resolution. No perfume-specific variant
    # names or aliases are present here.
    if not isinstance(result, dict):
        return result

    raw_name = str(result.get('name') or result.get('title') or '').strip()
    raw_brand = str(result.get('brand') or result.get('manufacturer') or '').strip()

    try:
        if PRODUCT_MATCHER is not None and PRODUCT_MATCHER._is_non_fragrance_offer(result):
            print(
                f'PRODUCT_MATCHER_NON_FRAGRANCE_REJECT: '
                f'name={raw_name!r} brand={raw_brand!r}',
                flush=True,
            )
            return None

        if not query or CATALOG_IDENTITY_RESOLVER is None:
            return result

        matched = CATALOG_IDENTITY_RESOLVER.match(result, query)

        # Unresolved legitimate offers are preserved. The catalog grows over
        # time; lack of a catalog identity must never invent or delete a result.
        if matched is None:
            return result

        normalized = dict(matched)
        if raw_name:
            normalized.setdefault('_source_name', raw_name)
        if raw_brand:
            normalized.setdefault('_source_brand', raw_brand)

        canonical_name = str(
            normalized.get('canonical_name')
            or normalized.get('catalog_variant')
            or raw_name
        ).strip()
        canonical_brand = str(
            normalized.get('canonical_brand')
            or normalized.get('brand')
            or raw_brand
        ).strip()

        if canonical_name:
            normalized['name'] = canonical_name
        if canonical_brand:
            normalized['brand'] = canonical_brand

        print(
            'SCENTHUNTER: CATALOG_IDENTITY '
            f'query={query!r} raw_name={raw_name!r} '
            f'canonical_name={canonical_name!r} '
            f'canonical_brand={canonical_brand!r} '
            f'method={normalized.get("match_method")} '
            f'score={normalized.get("match_score")}',
            flush=True,
        )
        return normalized

    except Exception as exc:
        print(
            f'PRODUCT_MATCHER_IDENTITY_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return result

def clean_result(item, store, query=''):
    result = dict(item)
    machine_store = _normalise_store(result.get('store') or result.get('shop'), store)

    if machine_store == 'easycosmetic':
        easycosmetic_name = str(
            result.get('name') or result.get('title') or ''
        ).strip().lower()
        if easycosmetic_name == 'anmelden':
            return None

    raw_name = str(result.get('name') or result.get('title') or '').strip().lower()
    if machine_store == 'parfumcity' and 'hawas' in raw_name and 'sample' in raw_name:
        return None

    if 'hawas' in raw_name:
        result_name = str(result.get('name') or result.get('title') or '').strip()
        result_name = re.sub(
            r'\s+(?:dames|heren|damen|herren)$',
            '',
            result_name,
            flags=re.IGNORECASE,
        )
        if result_name:
            result['name'] = result_name

    if machine_store == 'parfumcity' and not result.get('image'):
        source = result.get('source')
        if isinstance(source, dict) and source.get('image'):
            result['image'] = source.get('image')

    result['store'] = STORE_LABELS.get(machine_store, machine_store)
    result['shop'] = STORE_LABELS.get(machine_store, machine_store)
    if 'available' not in result and 'in_stock' in result:
        result['available'] = bool(result.get('in_stock'))
    if result.get('size_ml') in (None, ''):
        for key in ('volume_ml','format_ml','size'):
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
    return _apply_product_identity(result, query)

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

def dedupe_results(results):
    seen=set()
    output=[]
    for item in results:
        key=result_key(item)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output

def sort_results(results):
    def key(item):
        available=item.get('available')
        price=_safe_float(item.get('price_num'))
        rank=2 if available is False else 0 if price is not None else 1
        return rank, price if price is not None else 999999.0
    return sorted(results, key=key)

def _empty_report(store, status='error', elapsed=0.0, error=None):
    return {
        'store':store,
        'status':status,
        'elapsed':round(elapsed,3),
        'count':0,
        'results':[],
        'error':error
    }

def load_scraper(store):
    return importlib.import_module(f'scrapers.{store}.scraper')

def run_store(store, query):
    started=time.monotonic()
    try:
        search=getattr(load_scraper(store),'search',None)
        if not callable(search):
            raise RuntimeError(f'scraper {store} non espone search(query)')
        raw=search(query)
        if store=='parfumzentrum' and not raw:
            time.sleep(.25)
            raw=search(query)
        rows=[] if raw is None else list(raw) if not isinstance(raw, list) else raw
        cleaned=[
            cleaned
            for x in rows
            if isinstance(x,dict)
            for cleaned in [clean_result(x,store,query)]
            if cleaned is not None
        ]
        return {
            'store':store,
            'status':'ok' if cleaned else 'empty',
            'elapsed':round(time.monotonic()-started,3),
            'count':len(cleaned),
            'results':cleaned,
            'error':None
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

WORKER_CODE = r"""
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
                rows.append(row)
                emit('result',row=row)
        returned=stream(query,on_result)
        if returned is not None:
            try:
                for row in returned:
                    if isinstance(row,dict):
                        emit('result',row=row)
                        rows.append(row)
            except TypeError:
                pass
        emit('done',count=len(rows),streaming=True)
    else:
        search=getattr(module,'search',None)
        if not callable(search):
            raise RuntimeError(f'scraper {store} non espone search(query)')
        raw=search(query)
        if raw is None:
            rows=[]
        elif isinstance(raw,list):
            rows=raw
        elif isinstance(raw,tuple):
            rows=list(raw)
        else:
            try:
                rows=list(raw)
            except TypeError:
                rows=[]
        for row in rows:
            if isinstance(row,dict):
                emit('result',row=row)
        emit('done',count=len(rows),streaming=False)
except BaseException as exc:
    emit('error',error=f'{type(exc).__name__}: {exc}')
    raise SystemExit(1)
"""

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
    started=time.monotonic()
    timeout=STORE_TIMEOUTS.get(store,STORE_TIMEOUT_SECONDS)
    env=os.environ.copy()
    current=env.get('PYTHONPATH','')
    env['PYTHONPATH']=str(BASE_DIR)+(os.pathsep+current if current else '')
    process=None
    rows=[]
    worker_error=None
    try:
        process=subprocess.Popen(
            [sys.executable,'-u','-c',WORKER_CODE,store,query],
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
            start_new_session=(os.name!='nt')
        )
        deadline=time.monotonic()+timeout
        while True:
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(process.args,timeout)
            line=process.stdout.readline() if process.stdout is not None else ''
            if not line:
                if process.poll() is not None:
                    break
                time.sleep(0.01)
                continue
            try:
                event=json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(event,dict):
                continue
            kind=event.get('event')
            if kind=='result' and isinstance(event.get('row'),dict):
                row=clean_result(event['row'],store,query)
                if row is None:
                    continue
                rows.append(row)
                if callable(on_result):
                    on_result(row)
            elif kind=='error':
                worker_error=str(event.get('error') or 'worker_error')
        rc=process.wait(timeout=1)
        elapsed=round(time.monotonic()-started,3)
        if rc!=0 or worker_error:
            return {
                'store':store,
                'status':'error',
                'elapsed':elapsed,
                'count':len(rows),
                'results':rows,
                'error':worker_error or f'worker_exit_{rc}'
            }
        return {
            'store':store,
            'status':'ok' if rows else 'empty',
            'elapsed':elapsed,
            'count':len(rows),
            'results':rows,
            'error':None
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
            elapsed=round(time.monotonic()-started,3),
            error=f'store_timeout_{timeout:.0f}s'
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
            elapsed=round(time.monotonic()-started,3),
            error=f'{type(exc).__name__}: {exc}'
        )

def _run_controlled_store(store,query,on_report,on_result=None):
    print(f'STORE START store={store} query={query!r}',flush=True)
    semaphore=LIGHT_SEMAPHORE
    lane='light'
    if store in BROWSER_STORES:
        semaphore=BROWSER_SEMAPHORE
        lane='browser'
    elif store in NETWORK_HEAVY_STORES:
        semaphore=NETWORK_SEMAPHORE
        lane='network'
    wait=time.monotonic()
    if semaphore is not None:
        if not semaphore.acquire(timeout=JOB_TIMEOUT_SECONDS):
            report=_empty_report(store,error=f'{lane}_lane_unavailable')
            print(f'STORE TIMEOUT store={store} timeout=lane_wait',flush=True)
            on_report(report)
            return
        waited=round(time.monotonic()-wait,3)
        if waited>.1:
            print(f'STORE QUEUED store={store} lane={lane} waited={waited}',flush=True)
    try:
        report=_run_store_subprocess(store,query,on_result=on_result)
    finally:
        if semaphore is not None:
            semaphore.release()
    if report.get('status')=='error':
        if str(report.get('error','')).startswith('store_timeout_'):
            print(f"STORE TIMEOUT store={store} timeout={report['error']}",flush=True)
        else:
            print(f"STORE ERROR store={store} error={report.get('error')}",flush=True)
    print(
        f"STORE END store={store} status={report.get('status')} "
        f"elapsed={report.get('elapsed')} count={report.get('count')}",
        flush=True
    )
    on_report(report)

def collect_store_reports_isolated(query,stores,on_report=None,on_result=None):
    requested=list(stores)
    reports={}
    lock=threading.Lock()
    threads=[]

    def publish(report):
        with lock:
            reports[report['store']]=report
        if callable(on_report):
            on_report(report)

    for store in requested:
        t=threading.Thread(
            target=_run_controlled_store,
            args=(store,query,publish,on_result),
            daemon=True,
            name=f'scenthunter-store-{store}'
        )
        t.start()
        threads.append(t)

    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in threads:
        t.join(timeout=max(0.0,deadline-time.monotonic()))

    unfinished=[
        t.name.rsplit('scenthunter-store-',1)[-1]
        for t in threads
        if t.is_alive()
    ]
    if unfinished:
        print(f'SEARCH SUPERVISORS STILL RUNNING stores={unfinished}',flush=True)
        with lock:
            for store in unfinished:
                reports.setdefault(
                    store,
                    _empty_report(
                        store,
                        elapsed=JOB_TIMEOUT_SECONDS,
                        error='job_timeout'
                    )
                )
    return [reports[s] for s in requested if s in reports]

JOBS={}
JOBS_LOCK=threading.Lock()

def _new_job(query):
    job_id=uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id]={
            'job_id':job_id,
            'query':query,
            'started_at':time.time(),
            'completed':False,
            'results':[],
            'comparisons':[],
            'errors':{},
            'stores':{}
        }
    return job_id

def _snapshot(job_id):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job:
            return {
                'job_id':job_id,
                'query':'',
                'completed':True,
                'status':'completed',
                'count':0,
                'results':[],
                'comparisons':[],
                'errors':{'job':'job_not_found'},
                'stores':{}
            }
        return {
            'job_id':job['job_id'],
            'query':job['query'],
            'completed':job['completed'],
            'status':'completed' if job['completed'] else 'searching',
            'count':len(job['results']),
            'results':list(job['results']),
            'comparisons':list(job['comparisons']),
            'errors':dict(job['errors']),
            'stores':dict(job['stores'])
        }

def _publish_result(job_id,row):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'):
            return
        clean=clean_result(
            row,
            row.get('store') or row.get('shop') or '',
            job.get('query') or ''
        )
        if clean is None or not _keep_hawas_result(clean, job.get('query')):
            return
        job['results'].append(clean)
        job['results']=sort_results(dedupe_results(job['results']))
        total=len(job['results'])
    print(
        f"SEARCH PUBLISH RESULT job={job_id} "
        f"store={clean.get('store')} total={total}",
        flush=True
    )

def _publish_store(job_id,report):
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if not job or job.get('completed'):
            return
        store=report['store']
        job['stores'][store]={
            'status':report['status'],
            'elapsed':report['elapsed'],
            'count':report['count']
        }
        if report.get('error'):
            job['errors'][store]=report['error']
        if report.get('results'):
            job['results'].extend(
                x for x in report['results']
                if _keep_hawas_result(x, job.get('query'))
            )
        job['results']=sort_results(dedupe_results(job['results']))
        total=len(job['results'])
    print(
        f"SEARCH PUBLISH job={job_id} store={store} "
        f"count={report.get('count')} total={total}",
        flush=True
    )

def _collect_streaming_for_job(job_id,query,stores):
    reports={}
    lock=threading.Lock()
    threads=[]

    def publish(report):
        with lock:
            reports[report['store']]=report
        _publish_store(job_id,report)

    def publish_row(row):
        _publish_result(job_id,row)

    for store in stores:
        t=threading.Thread(
            target=_run_controlled_store,
            args=(store,query,publish,publish_row),
            daemon=True,
            name=f'scenthunter-store-{store}'
        )
        t.start()
        threads.append(t)

    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in threads:
        t.join(timeout=max(0.0,deadline-time.monotonic()))

    return [reports[s] for s in stores if s in reports]

def _run_job(job_id,query):
    started=time.monotonic()
    print(f'SEARCH START job={job_id} query={query!r}',flush=True)
    collect_store_reports_isolated(
        query,
        STORES,
        on_report=lambda r:_publish_store(job_id,r),
        on_result=lambda row:_publish_result(job_id,row)
    )
    with JOBS_LOCK:
        job=JOBS.get(job_id)
        if job:
            job['results']=sort_results(dedupe_results(job['results']))
            job['completed']=True
            job['elapsed']=round(time.monotonic()-started,3)
            elapsed=job['elapsed']
            total=len(job['results'])
        else:
            elapsed=round(time.monotonic()-started,3)
            total=0
    print(f'SEARCH END job={job_id} elapsed={elapsed} total={total}',flush=True)

@app.get('/',include_in_schema=False)
def root():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {
        'app':'ScentHunter',
        'status':'running',
        'architecture':APP_VERSION,
        'error':'frontend/index.html not found'
    }

@app.get('/health')
def health():
    return {
        'status':'healthy',
        'architecture':APP_VERSION,
        'stores':STORES,
        'lightweight_stores':LIGHTWEIGHT_STORES,
        'network_heavy_stores':NETWORK_HEAVY_STORES,
        'browser_stores':BROWSER_STORES,
        'light_workers':LIGHT_WORKERS,
        'network_workers':NETWORK_WORKERS,
        'browser_workers':BROWSER_WORKERS,
        'store_timeouts':STORE_TIMEOUTS,
        'job_timeout':JOB_TIMEOUT_SECONDS
    }

@app.get('/search-start')
def search_start(q:str):
    query=str(q or '').strip()
    if not query:
        return {
            'job_id':'',
            'query':'',
            'completed':True,
            'status':'completed',
            'count':0,
            'results':[],
            'comparisons':[],
            'errors':{},
            'stores':{}
        }
    job_id=_new_job(query)
    threading.Thread(
        target=_run_job,
        args=(job_id,query),
        daemon=True,
        name=f'scenthunter-search-{job_id[:8]}'
    ).start()
    return _snapshot(job_id)

@app.get('/search-status/{job_id}')
def search_status_path(job_id:str):
    return _snapshot(job_id)

@app.get('/search-status')
def search_status_query(job_id:str):
    return _snapshot(job_id)

@app.get('/search')
def search_perfume(q:str):
    query=str(q or '').strip()
    if not query:
        return {'query':'','count':0,'results':[],'errors':{},'stores':{}}

    reports=collect_store_reports_isolated(query,STORES)
    all_results=[]
    for report in reports:
        all_results.extend(report['results'])
    results=sort_results(dedupe_results(all_results))

    return {
        'query':query,
        'count':len(results),
        'results':results,
        'errors':{
            r['store']:r['error']
            for r in reports
            if r.get('error')
        },
        'stores':{
            r['store']:{
                'status':r['status'],
                'count':r['count'],
                'elapsed':r['elapsed']
            }
            for r in reports
        }
    }

@app.get('/test-store')
def test_store(store:str,q:str):
    store=str(store or '').strip().lower()
    query=str(q or '').strip()
    if store not in STORES:
        return {
            'ok':False,
            'store':store,
            'query':query,
            'error':'unknown_store',
            'stores':STORES
        }
    report=run_store(store,query)
    return {'ok':report['status']!='error','store':store,'query':query,**report}

@app.get('/diagnose-stores')
def diagnose_stores(q:str='Liquid Brun'):
    query=str(q or '').strip()
    if not query:
        return {
            'ok':False,
            'query':'',
            'stores':[],
            'total_count':0,
            'architecture':APP_VERSION
        }
    reports=collect_store_reports_isolated(query,STORES)
    by_store={r['store']:r for r in reports}
    ordered=[by_store[s] for s in STORES if s in by_store]
    return {
        'ok':True,
        'architecture':APP_VERSION,
        'query':query,
        'stores':ordered,
        'total_count':sum(r.get('count',0) for r in ordered)
    }

@app.get('/diagnose-sabina')
def diagnose_sabina(q:str='Liquid Brun'):
    query=str(q or '').strip()
    started=time.monotonic()
    report={
        'ok':True,
        'architecture':APP_VERSION,
        'query':query,
        'elapsed':0.0,
        'module':{},
        'direct_search':{},
        'stream_search':{}
    }
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))

        try:
            import sitecustomize as _sitecustomize
            importlib.reload(_sitecustomize)
            report['sitecustomize']={
                'loaded':True,
                'module':getattr(_sitecustomize,'__file__',None)
            }
        except Exception as exc:
            report['sitecustomize']={
                'loaded':False,
                'error':f'{type(exc).__name__}: {exc}'
            }

        module=load_scraper('sabina')
        report['module']={
            'module':getattr(module,'__file__',None),
            'BASE_URL':getattr(module,'BASE_URL',None),
            'BASE':getattr(module,'BASE',None),
            '_clean':callable(getattr(module,'_clean',None)),
            'clean':callable(getattr(module,'clean',None)),
            'search':callable(getattr(module,'search',None)),
            'search_stream':callable(getattr(module,'search_stream',None))
        }

        try:
            t=time.monotonic()
            raw=module.search(query)
            rows=[] if raw is None else list(raw) if not isinstance(raw,list) else raw
            report['direct_search']={
                'elapsed':round(time.monotonic()-t,3),
                'count':len(rows),
                'results':[
                    clean_result(x,'sabina',query)
                    for x in rows
                    if isinstance(x,dict)
                ]
            }
        except Exception as exc:
            report['direct_search']={
                'elapsed':round(time.monotonic()-t,3),
                'count':0,
                'error':f'{type(exc).__name__}: {exc}'
            }

        stream=getattr(module,'search_stream',None)
        if callable(stream):
            stream_rows=[]
            t=time.monotonic()

            def collect(row):
                if isinstance(row,dict):
                    stream_rows.append(clean_result(row,'sabina',query))

            try:
                returned=stream(query,collect)
                if returned is not None:
                    try:
                        for row in returned:
                            if isinstance(row,dict):
                                stream_rows.append(clean_result(row,'sabina',query))
                    except TypeError:
                        pass

                report['stream_search']={
                    'elapsed':round(time.monotonic()-t,3),
                    'count':len(stream_rows),
                    'results':stream_rows
                }
            except Exception as exc:
                report['stream_search']={
                    'elapsed':round(time.monotonic()-t,3),
                    'count':len(stream_rows),
                    'results':stream_rows,
                    'error':f'{type(exc).__name__}: {exc}'
                }
        else:
            report['stream_search']={
                'elapsed':0.0,
                'count':0,
                'error':'search_stream_missing'
            }
    except Exception as exc:
        report['ok']=False
        report['error']=f'{type(exc).__name__}: {exc}'

    report['elapsed']=round(time.monotonic()-started,3)
    return report

@app.get('/suggest')
def suggest(q:str):
    query=str(q or '').strip()
    if len(query)<2:
        return {'query':query,'count':0,'suggestions':[]}

    suggestions=[]
    seen=set()
    reports=collect_store_reports_isolated(query,LIGHTWEIGHT_STORES[:4])

    for report in reports:
        for item in report.get('results',[]):
            name=str(item.get('name') or item.get('title') or '').strip()
            brand=str(item.get('brand') or '').strip()
            if not name:
                continue
            key=f'{brand}|{name}'.lower()
            if key in seen:
                continue
            seen.add(key)
            suggestions.append({'brand':brand,'name':name})
            if len(suggestions)>=8:
                break
        if len(suggestions)>=8:
            break

    return {
        'query':query,
        'count':len(suggestions),
        'suggestions':suggestions[:8]
    }

@app.get('/frontend')
def frontend():
    if FRONTEND_INDEX.exists():
        return FileResponse(FRONTEND_INDEX)
    return {'error':'frontend/index.html not found'}

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib, json, os, re, signal, subprocess, sys, threading, time, traceback, uuid, unicodedata
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


class _CatalogIdentityResolver:
    """
    Generic catalog-only identity resolver.

    IMPORTANT: this layer resolves an offer to ONE catalog product before the
    frontend is allowed to group it.  It never contains product/variant names.
    Exact catalog aliases always beat fuzzy matching.  Fuzzy matching is only
    a conservative fallback for retailer formatting noise.
    """
    COMMERCIAL_NOISE = {
        'refill', 'refillable', 'refilled', 'nachfullbar', 'nachfullung',
        'nachfuellbar', 'nachfuellung', 'nachfullen', 'nachfuellen',
        'rechargeable', 'recharge', 'wiederbefullbar', 'wiederbefuellbar',
        'new', 'neu',
    }
    RELAXED_CONCENTRATION = {
        'eau', 'de', 'toilette', 'parfum', 'cologne', 'fraiche',
        'extrait', 'edp', 'edt', 'edc', 'perfume', 'spray',
    }

    def __init__(self, matcher):
        self.matcher = matcher
        self.catalog = list(getattr(matcher, 'catalog', []) or [])
        self.brands = sorted(
            {self._norm(getattr(p, 'brand', '')) for p in self.catalog if self._norm(getattr(p, 'brand', ''))},
            key=lambda x: (-len(x.split()), -len(x)),
        )

        # Alias indexes are built once from the catalog.  This is the critical
        # distinction from fuzzy-only matching: "Bottled Infinite" can only
        # resolve to a catalog product whose alias actually says that.
        self._strict_aliases = {}
        self._relaxed_aliases = {}
        for product in self.catalog:
            for form in self._forms(product):
                strict = self._identity_key(form, getattr(product, 'brand', ''), relaxed=False)
                relaxed = self._identity_key(form, getattr(product, 'brand', ''), relaxed=True)
                if strict:
                    self._strict_aliases.setdefault(strict, []).append(product)
                if relaxed:
                    self._relaxed_aliases.setdefault(relaxed, []).append(product)

    @staticmethod
    def _norm(value):
        text = str(value or '').strip().lower()
        text = unicodedata.normalize('NFKD', text)
        text = ''.join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r'[^a-z0-9]+', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    @classmethod
    def _tokens(cls, value, remove_noise=True):
        text = cls._norm(value)
        text = re.sub(r'\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz)\b', ' ', text)
        tokens = text.split()
        if remove_noise:
            tokens = [t for t in tokens if t not in cls.COMMERCIAL_NOISE]
        return tokens

    @classmethod
    def _forms(cls, product):
        values = [getattr(product, 'name', ''), getattr(product, 'family_name', '')]
        values.extend(getattr(product, 'aliases', ()) or ())
        return [str(v).strip() for v in values if str(v or '').strip()]

    @classmethod
    def _remove_brand_tokens(cls, tokens, brand):
        result = list(tokens)
        for token in cls._norm(brand).split():
            try:
                result.remove(token)
            except ValueError:
                pass
        return result

    @classmethod
    def _identity_key(cls, value, brand='', relaxed=False):
        tokens = cls._tokens(value, remove_noise=True)
        tokens = cls._remove_brand_tokens(tokens, brand)
        if relaxed:
            # Remove only multi-word concentration descriptors and common
            # retailer concentration abbreviations.  Bare "parfum" is kept:
            # it can be a real variant name (e.g. Boss Bottled Parfum).
            text = ' '.join(tokens)
            text = re.sub(
                r'\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|'
                r'eau\s+de\s+cologne|eau\s+fraiche|'
                r'extrait\s+de\s+parfum|edp|edt|edc|perfume|spray)\b',
                ' ', text, flags=re.I,
            )
            tokens = [t for t in cls._norm(text).split() if t not in cls.COMMERCIAL_NOISE]
        return ' '.join(tokens).strip()

    @staticmethod
    def _subsequence(container, sequence):
        if not sequence:
            return True
        pos = 0
        for token in container:
            if token == sequence[pos]:
                pos += 1
                if pos == len(sequence):
                    return True
        return False

    @staticmethod
    def _f_score(left, right):
        a, b = set(left), set(right)
        if not a or not b:
            return 0.0
        hit = len(a & b)
        precision = hit / len(a)
        recall = hit / len(b)
        return (2 * precision * recall / (precision + recall)) if precision + recall else 0.0

    @classmethod
    def _conservative_score(cls, offer_tokens, candidate_tokens):
        if not offer_tokens or not candidate_tokens:
            return 0.0
        if offer_tokens == candidate_tokens:
            return 1.0

        # The only tolerated structural difference is an omitted duplicated
        # brand token.  We do NOT let a partial overlap promote a different
        # variant.  This is what previously allowed Infinite/Tonic/etc. to
        # leak into the base Bottled card.
        if cls._subsequence(candidate_tokens, offer_tokens):
            unmatched = [t for t in candidate_tokens if t not in offer_tokens]
            if all(t in {'boss', 'hugo'} for t in unmatched):
                return 0.94

        f = cls._f_score(offer_tokens, candidate_tokens)
        if f >= 0.90:
            return 0.90 + 0.05 * f
        return 0.0

    def _query_scope(self, query):
        query_tokens = self._tokens(query)
        if not query_tokens:
            return list(self.catalog)

        query_set = set(query_tokens)
        query_brand = ''
        for brand in self.brands:
            bt = brand.split()
            if bt and set(bt).issubset(query_set):
                query_brand = brand
                break
        query_core = self._remove_brand_tokens(query_tokens, query_brand)

        scoped = []
        for product in self.catalog:
            product_brand = self._norm(getattr(product, 'brand', ''))
            if query_brand and product_brand != query_brand:
                continue
            if not query_core:
                scoped.append(product)
                continue
            for form in self._forms(product):
                form_tokens = self._remove_brand_tokens(self._tokens(form), product_brand)
                if set(query_core).issubset(set(form_tokens)):
                    scoped.append(product)
                    break
        return scoped

    @staticmethod
    def _offer_forms(result):
        forms = [
            str(result.get('name') or ''),
            str(result.get('title') or ''),
            str(result.get('product_name') or ''),
        ]
        source = result.get('source')
        if isinstance(source, dict):
            forms.extend([
                str(source.get('source_name') or ''),
                str(source.get('name') or ''),
                str(source.get('title') or ''),
            ])
        return [x for x in forms if x.strip()]

    def _exact_catalog_match(self, offer_forms, offer_brand, scope):
        strict_hits = []
        relaxed_hits = []
        for form in offer_forms:
            strict_key = self._identity_key(form, offer_brand, relaxed=False)
            relaxed_key = self._identity_key(form, offer_brand, relaxed=True)
            if strict_key:
                strict_hits.extend(self._strict_aliases.get(strict_key, []))
            if relaxed_key:
                relaxed_hits.extend(self._relaxed_aliases.get(relaxed_key, []))

        scope_ids = {id(p) for p in scope}
        strict_unique = []
        for product in strict_hits:
            if id(product) in scope_ids and product not in strict_unique:
                strict_unique.append(product)
        if len(strict_unique) == 1:
            return strict_unique[0], 'catalog_alias_exact', 1.0
        if len(strict_unique) > 1:
            # Ambiguous aliases are never resolved by guessing.
            return None, 'ambiguous', 0.0

        relaxed_unique = []
        for product in relaxed_hits:
            if id(product) in scope_ids and product not in relaxed_unique:
                relaxed_unique.append(product)
        if len(relaxed_unique) == 1:
            return relaxed_unique[0], 'catalog_alias_relaxed', 0.97
        return None, 'none', 0.0

    def _url_identity_conflict(self, result, matched):
        """Reject a link only when its URL clearly names another catalog variant.

        Generic protection against the exact failure mode where a retailer
        card is labelled as one variant but its href points to another.
        Numeric/product-id URLs and URLs without a recognizable product name
        are left untouched.
        """
        urls = []
        # Both the destination URL and the image URL are identity-bearing
        # retailer data when they contain a readable product slug/name.
        # Generic CDN hashes are ignored naturally because they do not match
        # any catalog identity signature.
        for key in ('url', 'product_url', 'link', 'image', 'image_url', 'thumbnail'):
            value = result.get(key)
            if value:
                urls.append(str(value))
        source = result.get('source')
        if isinstance(source, dict):
            for key in ('url', 'product_url', 'link', 'image', 'image_url', 'thumbnail'):
                value = source.get(key)
                if value:
                    urls.append(str(value))
        if not urls:
            return False

        matched_id = str(getattr(matched, 'catalog_id', '') or '')
        matched_brand = self._norm(getattr(matched, 'brand', ''))
        conflicts = []

        for raw_url in urls:
            url_key = self._norm(raw_url)
            if not url_key or len(url_key.split()) < 2:
                continue
            url_tokens = url_key.split()
            for product in self.catalog:
                pid = str(getattr(product, 'catalog_id', '') or '')
                if pid and matched_id and pid == matched_id:
                    continue
                if matched_brand and self._norm(getattr(product, 'brand', '')) != matched_brand:
                    continue
                for form in self._forms(product):
                    core = self._identity_key(form, getattr(product, 'brand', ''), relaxed=True)
                    if not core:
                        continue
                    core_tokens = core.split()
                    # Require at least two identity tokens so a generic word
                    # such as "bottled" cannot flag an unrelated URL.
                    if len(core_tokens) < 2:
                        continue
                    if self._subsequence(url_tokens, core_tokens):
                        conflicts.append(product)
                        break
                if conflicts and conflicts[-1] is product:
                    break

        unique = {str(getattr(p, 'catalog_id', '') or id(p)) for p in conflicts}
        return bool(unique) and any(
            str(getattr(p, 'catalog_id', '') or '') != matched_id
            for p in conflicts
        )

    def resolve(self, result, query):
        if not isinstance(result, dict) or not query or not self.catalog:
            return None

        raw_name = str(result.get('name') or result.get('title') or result.get('product_name') or '').strip()
        raw_brand = str(result.get('brand') or result.get('manufacturer') or '').strip()
        if not raw_name:
            return None

        scope = self._query_scope(query)
        if not scope:
            return None

        offer_brand = self._norm(raw_brand)
        offer_forms = self._offer_forms(result)

        # 1) Exact catalog alias.  This is the normal path.
        exact, method, score = self._exact_catalog_match(offer_forms, offer_brand, scope)
        if exact is not None:
            if self._url_identity_conflict(result, exact):
                return {'_identity_conflict': True}
            return self._build(result, exact, method, score)
        if method == 'ambiguous':
            return None

        # 2) Conservative fallback.  No partial-overlap promotion of a
        # different variant is allowed.  If we cannot establish identity,
        # leave the retailer result untouched rather than mislabelling it.
        best = None
        best_score = 0.0
        for product in scope:
            product_brand = self._norm(getattr(product, 'brand', ''))
            if offer_brand and product_brand and offer_brand != product_brand:
                continue
            candidate_tokens = []
            for form in self._forms(product):
                candidate_tokens.extend(self._remove_brand_tokens(self._tokens(form), product_brand))
            candidate_tokens = list(dict.fromkeys(candidate_tokens))
            for form in offer_forms:
                offer_tokens = self._remove_brand_tokens(self._tokens(form), product_brand)
                score_here = self._conservative_score(offer_tokens, candidate_tokens)
                if score_here > best_score:
                    best = product
                    best_score = score_here

        if best is None or best_score < 0.90:
            return None
        if self._url_identity_conflict(result, best):
            return {'_identity_conflict': True}
        return self._build(result, best, 'catalog_variant_conservative', best_score)

    @staticmethod
    def _build(result, product, method, score):
        normalized = dict(result)
        canonical_name = str(getattr(product, 'name', '') or '').strip()
        canonical_brand = str(getattr(product, 'brand', '') or '').strip()
        normalized.update({
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
        raw_name = str(result.get('name') or result.get('title') or result.get('product_name') or '').strip()
        raw_brand = str(result.get('brand') or result.get('manufacturer') or '').strip()
        if raw_name:
            normalized['_source_name'] = raw_name
        if raw_brand:
            normalized['_source_brand'] = raw_brand
        if canonical_name:
            normalized['name'] = canonical_name
        if canonical_brand:
            normalized['brand'] = canonical_brand
        return normalized


CATALOG_IDENTITY_RESOLVER = _CatalogIdentityResolver(PRODUCT_MATCHER) if PRODUCT_MATCHER is not None else None


def _apply_product_identity(result, query=''):
    """Apply the generic catalog identity layer without product-specific rules."""
    if PRODUCT_MATCHER is None or not isinstance(result, dict):
        return result

    raw_name = str(result.get('name') or result.get('title') or '').strip()
    raw_brand = str(result.get('brand') or result.get('manufacturer') or '').strip()

    try:
        if PRODUCT_MATCHER._is_non_fragrance_offer(result):
            print(
                f'PRODUCT_MATCHER_NON_FRAGRANCE_REJECT: name={raw_name!r} brand={raw_brand!r}',
                flush=True,
            )
            return None

        if not query or CATALOG_IDENTITY_RESOLVER is None:
            return result

        matched = CATALOG_IDENTITY_RESOLVER.resolve(result, query)
        if isinstance(matched, dict) and matched.get('_identity_conflict'):
            print(
                f'PRODUCT_MATCHER_IDENTITY_CONFLICT_REJECT: name={raw_name!r} url={result.get("url")!r}',
                flush=True,
            )
            return None
        if matched is None:
            # Never delete a legitimate retailer result merely because the
            # catalog has no identity for it yet.
            return result
        return matched
    except Exception as exc:
        print(
            f'PRODUCT_MATCHER_CATEGORY_FILTER_ERROR: {type(exc).__name__}: {exc}',
            flush=True,
        )
        return result


def clean_result(item, store, query=''):
    result = dict(item)
    machine_store = _normalise_store(result.get('store') or result.get('shop'), store)

    # EASY COSMETIC ONLY:
    # Easycosmetic sometimes returns its account/login entry "Anmelden"
    # as a result card. It is not a product and its card cannot be opened.
    # Deliberately match ONLY this exact entry and ONLY this store.
    if machine_store == 'easycosmetic':
        easycosmetic_name = str(
            result.get('name') or result.get('title') or ''
        ).strip().lower()
        if easycosmetic_name == 'anmelden':
            return None

    # HAWAS P1: remove ParfumCity Hawas samples only.
    raw_name = str(result.get('name') or result.get('title') or '').strip().lower()
    if machine_store == 'parfumcity' and 'hawas' in raw_name and 'sample' in raw_name:
        return None

    # HAWAS P3: retailer gender suffixes are naming noise for the same
    # Hawas variant. Normalize only a trailing Dames/Heren/Damen/Herren.
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

    # P4: ParfumCity keeps its product image inside source.image instead of
    # exposing it at the top level. The frontend reads the top-level image
    # field when selecting the group's representative image. Promote ONLY
    # ParfumCity's existing source.image; never invent or fetch a new image.
    if machine_store == 'parfumcity' and not result.get('image'):
        source = result.get('source')
        if isinstance(source, dict) and source.get('image'):
            result['image'] = source.get('image')

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
                row=clean_result(event['row'],store,query)
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
        clean=clean_result(row,row.get('store') or row.get('shop') or '',job.get('query') or '')
        if clean is None or not _keep_hawas_result(clean, job.get('query')):
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
            job['results'].extend(
                x for x in report['results']
                if _keep_hawas_result(x, job.get('query'))
            )
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
            report['direct_search']={'elapsed':round(time.monotonic()-t,3),'count':len(rows),'results':[clean_result(x,'sabina',query) for x in rows if isinstance(x,dict)]}
        except Exception as exc:
            report['direct_search']={'elapsed':round(time.monotonic()-t,3),'count':0,'error':f'{type(exc).__name__}: {exc}'}
        stream=getattr(module,'search_stream',None)
        if callable(stream):
            stream_rows=[]; t=time.monotonic()
            def collect(row):
                if isinstance(row,dict): stream_rows.append(clean_result(row,'sabina',query))
            try:
                returned=stream(query,collect)
                if returned is not None:
                    try:
                        for row in returned:
                            if isinstance(row,dict): stream_rows.append(clean_result(row,'sabina',query))
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

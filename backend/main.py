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
APP_VERSION = '4.2-linear-store-contract'
app = FastAPI(title='ScentHunter API', version=APP_VERSION)

# Read-only scraper diagnostics. This module does not participate in normal search.
try:
    from diagnose_two_scrapers import router as diagnose_two_scrapers_router
    app.include_router(diagnose_two_scrapers_router)
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
        # ``None`` is the ProductMatcher's explicit unresolved/rejected result.
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
    r"decant(?:s)?|tester(?:s)?|testeur(?:s)?)(?:[^a-z0-9]|$)",
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

    if "price_num" not in result:
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
                canonical_brand = (
                    offer.get("canonical_brand")
                    or offer.get("brand")
                    or ""
                )
                canonical_name = (
                    offer.get("canonical_name")
                    or offer.get("name")
                    or ""
                )
                display_name = canonical_name
                if canonical_brand and canonical_name:
                    display_name = f"{canonical_brand} — {canonical_name}"
                elif canonical_brand:
                    display_name = canonical_brand

                groups[catalog_id] = {
                    "catalog_id": catalog_id,
                    "brand": canonical_brand,
                    "name": display_name,
                    "family": offer.get("family"),
                    "variant": offer.get("variant"),
                    "canonical_name": canonical_name,
                    "canonical_brand": canonical_brand,
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
        process=subprocess.Popen([sys.executable,'-u','-c',WORKER_CODE,store,query],cwd=str(BASE_DIR),env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=False,bufsize=0,start_new_session=(os.name!='nt'))
        deadline=time.monotonic()+timeout; stdout_buffer=b''
        while True:
            if cancel_event is not None and cancel_event.is_set():
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
        if process is not None:
            _kill_process_tree(process)
            try: process.communicate(timeout=2)
            except Exception: pass
        return _empty_report(store,status='timeout',elapsed=round(time.monotonic()-started,3),error=f'store_timeout_{timeout:.0f}s') | {'verified':False}
    except Exception as exc:
        if process is not None:
            _kill_process_tree(process)
            try: process.communicate(timeout=1)
            except Exception: pass
        return _empty_report(store,status='error',elapsed=round(time.monotonic()-started,3),error=f'{type(exc).__name__}: {exc}') | {'verified':False}


def _run_store_subprocess(store, query, on_result=None, cancel_event=None):
    """Retry results that are not safely classified by the store contract."""
    first=_run_store_subprocess_once(store,query,on_result=on_result,cancel_event=cancel_event)
    fs=first.get('status'); fv=bool(first.get('verified')); fc=int(first.get('count') or 0)
    if fv and (fs in {'ok','no_match'} or (fs=='partial' and fc>0)):
        first['attempts']=1
        return first
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
    if ss not in {'error','timeout','blocked','unavailable'}: second['status']='unavailable'
    if not second.get('error'): second['error']=f"store_unverified_after_retry:{second.get('status')}"
    return second

def _run_controlled_store(store,query,on_report,on_result=None,cancel_event=None):
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
            report=_empty_report(store,error=f'{lane}_lane_unavailable')
            print(f'STORE TIMEOUT store={store} timeout=lane_wait',flush=True); on_report(report); return
        waited=round(time.monotonic()-wait,3)
        if waited>.1: print(f'STORE QUEUED store={store} lane={lane} waited={waited}',flush=True)
    try: report=_run_store_subprocess(store,query,on_result=on_result,cancel_event=cancel_event)
    finally:
        if semaphore is not None: semaphore.release()
    if report.get('status')=='error':
        if str(report.get('error','')).startswith('store_timeout_'): print(f"STORE TIMEOUT store={store} timeout={report['error']}",flush=True)
        else: print(f"STORE ERROR store={store} error={report.get('error')}",flush=True)
    print(f"STORE END store={store} status={report.get('status')} elapsed={report.get('elapsed')} count={report.get('count')}",flush=True)
    on_report(report)

def collect_store_reports_isolated(query,stores,on_report=None,on_result=None,cancel_event=None):
    requested=list(stores); reports={}; lock=threading.Lock(); threads=[]
    def publish(report):
        with lock: reports[report['store']]=report
        if callable(on_report): on_report(report)
    for store in requested:
        t=threading.Thread(target=_run_controlled_store,args=(store,query,publish,on_result,cancel_event),daemon=True,name=f'scenthunter-store-{store}')
        t.start(); threads.append(t)
    deadline=time.monotonic()+JOB_TIMEOUT_SECONDS
    for t in threads: t.join(timeout=max(0.0,deadline-time.monotonic()))
    unfinished=[t.name.rsplit('scenthunter-store-',1)[-1] for t in threads if t.is_alive()]
    if unfinished:
        print(f'SEARCH SUPERVISORS CANCELLING stores={unfinished}',flush=True)
        if cancel_event is not None:
            cancel_event.set()
        cancel_deadline=time.monotonic()+3.0
        for t in threads:
            if t.is_alive():
                t.join(timeout=max(0.0,cancel_deadline-time.monotonic()))
        with lock:
            for store in unfinished: reports.setdefault(store,_empty_report(store,elapsed=JOB_TIMEOUT_SECONDS,error='job_timeout'))
    return [reports[s] for s in requested if s in reports]

JOBS={}; JOBS_LOCK=threading.Lock()

def _cancel_active_jobs():
    with JOBS_LOCK:
        active=[job for job in JOBS.values() if not job.get("completed")]
    for job in active:
        event=job.get("cancel_event")
        if event is not None:
            event.set()
    if active:
        print(f"SEARCH CANCEL REQUEST active_jobs={len(active)}",flush=True)

def _new_job(query):
    job_id=uuid.uuid4().hex
    with JOBS_LOCK: JOBS[job_id] = {
    "job_id": job_id,
    "query": query,
    "started_at": time.time(),
    "completed": False,
    "cancel_event": threading.Event(),

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
            "status": job.get("status") or (
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
            "elapsed": report["elapsed"],
            "count": report["count"],
            "details": dict(report.get("details") or {}),
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
    with JOBS_LOCK:
        current_job=JOBS.get(job_id)
    cancel_event=current_job.get("cancel_event") if current_job else None
    collect_store_reports_isolated(
        query,
        STORES,
        on_report=lambda r:_publish_store(job_id,r),
        on_result=lambda row:_publish_result(job_id,row),
        cancel_event=cancel_event,
    )
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
        cancelled=bool(job.get("cancel_event") and job["cancel_event"].is_set())
        job["completed"] = True
        job["status"] = "cancelled" if cancelled else "completed"
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

@app.get('/health')
def health():
    return {'status':'healthy','architecture':APP_VERSION,'stores':STORES,'lightweight_stores':LIGHTWEIGHT_STORES,'network_heavy_stores':NETWORK_HEAVY_STORES,'browser_stores':BROWSER_STORES,'light_workers':LIGHT_WORKERS,'network_workers':NETWORK_WORKERS,'browser_workers':BROWSER_WORKERS,'store_timeouts':STORE_TIMEOUTS,'job_timeout':JOB_TIMEOUT_SECONDS}

@app.get('/search-start')
def search_start(q:str):
    query=str(q or '').strip()
    if not query: return {'job_id':'','query':'','completed':True,'status':'completed','count':0,'results':[],'unresolved_offers':[],'identity_scope':[],'comparisons':[],'errors':{},'stores':{}}
    _cancel_active_jobs()
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

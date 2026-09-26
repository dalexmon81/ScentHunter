# ScentHunter V7 - catalog-first store index
#
# Design contract:
#   STORE DISCOVERY -> STORE CATALOG -> LOCAL SEARCH -> PRODUCT PAGE REFRESH
#
# Search never calls a retailer search endpoint. Discovery is a background job.
# This module keeps the public interface used by main.py stable:
#   STORES, STORE_LABELS, db, search_local, refresh_candidates,
#   store_status, sync_all
#
# V7 focuses on discovery reliability and observability. It separates:
#   1) HTTP transport
#   2) sitemap discovery
#   3) XML parsing
#   4) generic URL admission
#   5) catalog persistence
#
# No product-specific URLs, names, prices or matching rules are embedded here.

import gzip
import importlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'store_catalog.sqlite3'

STORES = {
    'bplatz': 'https://en.bplatz.de',
    'parfumcity': 'https://www.parfumcity.nl',
    'parfumzentrum': 'https://www.parfum-zentrum.de',
    'perfumemarket': 'https://www.perfumemarket.nl',
    'sabina': 'https://www.sabina.com',
    'orioudh': 'https://orioudh.com',
    'easycosmetic': 'https://www.easycosmetic.de',
    'deloox': 'https://www.deloox.com',
}

STORE_LABELS = {
    k: ''.join(x.capitalize() for x in k.replace('-', ' ').split())
    for k in STORES
}
STORE_LABELS.update({
    'parfumcity': 'ParfumCity',
    'parfumzentrum': 'ParfumZentrum',
    'perfumemarket': 'PerfumeMarket',
    'easycosmetic': 'Easycosmetic',
    'bplatz': 'Bplatz',
    'deloox': 'Deloox',
    'sabina': 'Sabina',
    'orioudh': 'Orioudh',
})

# Store-level discovery configuration only: official storefront hosts.
# Deloox has several official localized hosts; trying all of them is still
# catalog discovery, not product-specific logic.
DISCOVERY_BASES = {
    'deloox': (
        'https://www.deloox.com',
        'https://www.deloox.be',
        'https://www.deloox.nl',
        'https://www.deloox.lu',
        'https://www.deloox.es',
    ),
}

USER_AGENT = 'ScentHunterBot/7.0 (+price-comparison; catalog indexing)'
HTTP_TIMEOUT = 15
SITEMAP_TIMEOUT = 20
REFRESH_TIMEOUT = 10

SYNC_WORKERS = 8
REFRESH_WORKERS = 8

# Sitemap protocol limits are per discovered sitemap, not a product limit.
MAX_SITEMAPS_PER_STORE = 1000
MAX_SITEMAP_DEPTH = 10
MAX_URLS_PER_SITEMAP = 50000
MAX_TOTAL_DISCOVERED_URLS = 250000

# A single failed/partial discovery must never wipe a previously valid catalog.
# If a new catalog is implausibly smaller than the existing one, retain the old
# catalog and expose the result as DISCOVERY_PARTIAL instead.
MIN_REPLACEMENT_RATIO = 0.10
MIN_REPLACEMENT_ABSOLUTE = 100

# Generic product URL signals. Product-vs-category is still decided after page
# fetch; this only removes obvious non-product endpoints from a sitemap.
NON_PRODUCT_PATH = re.compile(
    r'/(?:search|suche|chercher|suchen|buscar|category|categorie|categoria|'
    r'categories|brand|brands|marca|marque|sitemap|login|account|cart|'
    r'checkout|blog|news|tag|tags|help|faq)(?:/|$)',
    re.I,
)

_thread_local = threading.local()


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def tokens(q):
    return [x for x in norm(q).split() if len(x) > 1]


def url_slug(url):
    p = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(p.path)
    path = re.sub(r'\.(?:html?|php)$', '', path, flags=re.I)
    path = re.sub(r'[-_/]+', ' ', path)
    return norm(path)


def _session():
    session = getattr(_thread_local, 'session', None)
    if session is None:
        session = requests.Session()
        session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'text/xml, application/xml, application/xhtml+xml, text/html;q=0.9, */*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.8,*;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        })
        _thread_local.session = session
    return session


def _decode_body(data, url=''):
    """Decode gzip by magic bytes too, because servers often mislabel it."""
    if not data:
        return b''
    raw = bytes(data)
    if raw[:2] == b'\x1f\x8b' or str(url).lower().split('?', 1)[0].endswith('.gz'):
        try:
            return gzip.decompress(raw)
        except Exception:
            # requests normally already decompresses gzip. If it did, keep raw.
            pass
    return raw


def _http_fetch(url, timeout=HTTP_TIMEOUT):
    """Fetch with redirects, compression handling and diagnostics."""
    response = _session().get(url, timeout=timeout, allow_redirects=True)
    data = _decode_body(response.content, response.url or url)
    content_type = response.headers.get('Content-Type', '')
    content_encoding = response.headers.get('Content-Encoding', '')
    return {
        'status': int(response.status_code),
        'url': response.url or url,
        'data': data,
        'content_type': content_type,
        'content_encoding': content_encoding,
        'length': len(data),
        'headers': dict(response.headers),
    }


def http_get(url, timeout=HTTP_TIMEOUT):
    """Compatibility wrapper retained for page refresh code and tests."""
    r = _http_fetch(url, timeout=timeout)
    return r['status'], r['url'], r['data']


def _diagnostic(resp, requested_url):
    if not resp:
        return 'NO_RESPONSE'
    status = resp.get('status')
    final = resp.get('url') or requested_url
    ctype = (resp.get('content_type') or '').split(';', 1)[0].strip().lower()
    length = resp.get('length', 0)
    if status >= 400:
        return f'HTTP_{status};final={final};type={ctype or "?"};bytes={length}'
    if not resp.get('data'):
        return f'EMPTY_BODY;status={status};final={final};type={ctype or "?"}'
    return f'OK;status={status};final={final};type={ctype or "?"};bytes={length}'


def db():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS store_urls(
        store TEXT NOT NULL, url TEXT NOT NULL, slug TEXT NOT NULL,
        lastmod TEXT, discovered_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(store,url))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_store_urls_slug ON store_urls(store,slug)')
    conn.execute('''CREATE TABLE IF NOT EXISTS store_products(
        store TEXT NOT NULL, url TEXT NOT NULL, name TEXT, brand TEXT, image TEXT,
        sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL, concentration TEXT, gender TEXT,
        price REAL, currency TEXT, availability TEXT, fetched_at REAL, fetch_status TEXT,
        PRIMARY KEY(store,url))''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_store_products_store_name ON store_products(store,name)')
    conn.execute('''CREATE TABLE IF NOT EXISTS sync_state(
        store TEXT PRIMARY KEY, status TEXT, started_at REAL, finished_at REAL,
        discovered_count INTEGER DEFAULT 0, fetched_count INTEGER DEFAULT 0, error TEXT)''')
    conn.commit()
    return conn


def _discovery_bases(store):
    return tuple(dict.fromkeys(DISCOVERY_BASES.get(store, (STORES[store],))))


def _standard_sitemap_roots(base):
    """Generic sitemap candidates. robots.txt remains the primary source."""
    base = base.rstrip('/')
    names = (
        'sitemap.xml',
        'sitemap_index.xml',
        'sitemap-index.xml',
        'sitemaps.xml',
        'sitemap.xml.gz',
        'sitemap_index.xml.gz',
        'sitemap-index.xml.gz',
        # A few legitimate platforms expose these names instead of sitemap.xml.
        'sitemapa.xml',
        'sitemapi.xml',
    )
    return [f'{base}/{name}' for name in names] + [f'{base}/v/sitemap.xml']


def _seed_sitemaps(store):
    """Collect sitemap roots from robots.txt plus generic standard candidates."""
    roots = []
    robots_diagnostics = []
    for base in _discovery_bases(store):
        base = base.rstrip('/')
        roots.extend(_standard_sitemap_roots(base))
        robots_url = base + '/robots.txt'
        try:
            resp = _http_fetch(robots_url, timeout=8)
            robots_diagnostics.append(_diagnostic(resp, robots_url))
            if resp['status'] < 400 and resp['data']:
                text = resp['data'].decode('utf-8', 'ignore')
                # robots directives are case-insensitive in practice.
                for raw in re.findall(r'(?im)^\s*sitemap\s*:\s*(\S+)', text):
                    raw = raw.strip().strip('<>')
                    if raw:
                        roots.append(urllib.parse.urljoin(robots_url, raw))
        except Exception as exc:
            robots_diagnostics.append(f'{type(exc).__name__}:{exc}')
    return list(dict.fromkeys(roots)), robots_diagnostics


def _xml_local(tag):
    return str(tag or '').rsplit('}', 1)[-1].lower()


def _parse_xml_entries(data, url=''):
    """Return [(kind, loc, lastmod)] for sitemapindex or urlset."""
    raw = _decode_body(data, url)
    if not raw:
        return [], 'EMPTY_XML'

    try:
        root = ET.fromstring(raw)
        kind = _xml_local(root.tag)
        if kind == 'sitemapindex':
            out = []
            for node in list(root):
                if _xml_local(node.tag) != 'sitemap':
                    continue
                loc = ''
                lastmod = ''
                for child in list(node):
                    ck = _xml_local(child.tag)
                    if ck == 'loc':
                        loc = (child.text or '').strip()
                    elif ck == 'lastmod':
                        lastmod = (child.text or '').strip()
                if loc:
                    out.append(('sitemap', loc, lastmod))
            return out, None if out else 'EMPTY_SITEMAP_INDEX'

        if kind == 'urlset':
            out = []
            for node in list(root):
                if _xml_local(node.tag) != 'url':
                    continue
                loc = ''
                lastmod = ''
                for child in list(node):
                    ck = _xml_local(child.tag)
                    if ck == 'loc':
                        loc = (child.text or '').strip()
                    elif ck == 'lastmod':
                        lastmod = (child.text or '').strip()
                if loc:
                    out.append(('url', loc, lastmod))
            return out, None if out else 'EMPTY_URLSET'

        return [], f'XML_ROOT_{kind or "UNKNOWN"}'
    except ET.ParseError as exc:
        # BeautifulSoup is only a fallback for malformed-but-readable XML.
        try:
            soup = BeautifulSoup(raw, 'xml')
            if soup.find('sitemapindex') or soup.find('sitemap'):
                out = []
                for node in soup.find_all('sitemap'):
                    loc = node.find('loc')
                    if loc and loc.get_text(strip=True):
                        last = node.find('lastmod')
                        out.append(('sitemap', loc.get_text(strip=True), last.get_text(strip=True) if last else ''))
                if out:
                    return out, None
            out = []
            for node in soup.find_all('url'):
                loc = node.find('loc')
                if loc and loc.get_text(strip=True):
                    last = node.find('lastmod')
                    out.append(('url', loc.get_text(strip=True), last.get_text(strip=True) if last else ''))
            if out:
                return out, None
        except Exception:
            pass
        return [], f'XML_PARSE_ERROR:{type(exc).__name__}'
    except Exception as exc:
        return [], f'XML_PARSE_ERROR:{type(exc).__name__}'


def _looks_product(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https') or p.fragment:
        return False
    if NON_PRODUCT_PATH.search(p.path):
        return False
    path = urllib.parse.unquote(p.path).rstrip('/')
    if not path or path == '/':
        return False
    # Query-only product URLs are accepted if the path is meaningful.
    slug = url_slug(url)
    return len(slug.split()) >= 2


def _fetch_sitemap(store, sm):
    try:
        resp = _http_fetch(sm, timeout=SITEMAP_TIMEOUT)
        status = resp['status']
        final = resp['url'] or sm
        if status >= 400:
            return sm, final, [], _diagnostic(resp, sm)

        data = resp['data']
        # Detect HTML/WAF responses before XML parsing. Some sites return HTTP 200
        # with an anti-bot page for sitemap URLs.
        ctype = (resp.get('content_type') or '').lower()
        sample = data[:512].lstrip().lower() if data else b''
        looks_html = (
            'text/html' in ctype or
            sample.startswith(b'<!doctype html') or
            sample.startswith(b'<html') or
            b'<html' in sample[:200]
        )
        if looks_html:
            return sm, final, [], f'HTML_RESPONSE;status={status};type={ctype or "?"};bytes={len(data)};final={final}'

        entries, parse_error = _parse_xml_entries(data, final)
        if parse_error:
            return sm, final, [], f'{parse_error};status={status};type={ctype or "?"};bytes={len(data)};final={final}'
        return sm, final, entries, None
    except requests.RequestException as exc:
        return sm, sm, [], f'HTTP_EXCEPTION:{type(exc).__name__}:{exc}'
    except Exception as exc:
        return sm, sm, [], f'EXCEPTION:{type(exc).__name__}:{exc}'


def _existing_count(store):
    conn = db()
    try:
        return int(conn.execute(
            'SELECT COUNT(*) c FROM store_urls WHERE store=? AND active=1', (store,)
        ).fetchone()['c'])
    finally:
        conn.close()


def _save_discovery(store, product_urls, started_at, diagnostics):
    now = time.time()
    new_count = len(product_urls)
    old_count = _existing_count(store)

    # Never replace a known catalog with a suspiciously tiny transient result.
    if old_count >= MIN_REPLACEMENT_ABSOLUTE and new_count < old_count * MIN_REPLACEMENT_RATIO:
        conn = db()
        detail = (
            f'partial_catalog_rejected;old={old_count};new={new_count};'
            f'visited={diagnostics["visited"]};successes={diagnostics["successes"]};'
            f'entries={diagnostics["entries"]};errors={diagnostics["errors"]}'
        )
        conn.execute(
            '''INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(store) DO UPDATE SET status=excluded.status,
               started_at=excluded.started_at,finished_at=excluded.finished_at,
               discovered_count=excluded.discovered_count,error=excluded.error''',
            (store, 'DISCOVERY_PARTIAL', started_at, now, new_count, 0, detail),
        )
        conn.commit()
        conn.close()
        return 'DISCOVERY_PARTIAL', new_count, detail

    conn = db()
    with conn:
        if new_count:
            conn.execute('UPDATE store_urls SET active=0 WHERE store=?', (store,))
            for url, lastmod in product_urls.items():
                conn.execute(
                    '''INSERT INTO store_urls(store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                       slug=excluded.slug,lastmod=excluded.lastmod,
                       discovered_at=excluded.discovered_at,active=1''',
                    (store, url, url_slug(url), lastmod, now),
                )
            status = 'DISCOVERY_OK'
            error = None
        else:
            status = 'DISCOVERY_EMPTY'
            error = (
                f'no_product_urls;visited={diagnostics["visited"]};'
                f'successes={diagnostics["successes"]};entries={diagnostics["entries"]};'
                f'errors={diagnostics["errors"]}'
            )

        conn.execute(
            '''INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(store) DO UPDATE SET status=excluded.status,
               started_at=excluded.started_at,finished_at=excluded.finished_at,
               discovered_count=excluded.discovered_count,error=excluded.error''',
            (store, status, started_at, now, new_count, 0, error),
        )
    conn.close()
    return status, new_count, error



# HTML catalog-discovery fallback. This is NOT user-query search. It is a
# background crawl of the retailer's own category/brand/navigation surfaces,
# used only when sitemap discovery yields no usable product URLs.
HTML_DISCOVERY_SEEDS = {
    'easycosmetic': (
        'https://www.easycosmetic.de/',
        'https://www.easycosmetic.de/parfum',
        'https://www.easycosmetic.de/alle-marken',
        'https://www.easycosmetic.de/parfum-marken',
    ),
    'deloox': (
        'https://www.deloox.com/',
        'https://www.deloox.be/categorie/1075744/eau-de-toilette-homme.html',
        'https://www.deloox.be/categorie/1075743/eau-de-parfum-femme.html',
        'https://www.deloox.be/en/category/1103659/fragrances.html',
        'https://www.deloox.be/category/1075660/womens-perfume.html',
        'https://www.deloox.be/category/1075750/mens-perfume.html',
    ),
}
HTML_MAX_PAGES = 300
HTML_MAX_DEPTH = 5
HTML_WORKERS = 12
DISCOVERY_HARD_TIMEOUT = 240


def _html_product_url(store, raw_url, base_url):
    if not raw_url:
        return None
    absolute = urllib.parse.urljoin(base_url, raw_url).split('#', 1)[0]
    p = urllib.parse.urlparse(absolute)
    if p.scheme not in ('http', 'https'):
        return None
    allowed_hosts = {urllib.parse.urlparse(x).netloc.lower() for x in _discovery_bases(store)}
    if p.netloc.lower() not in allowed_hosts:
        return None
    path = p.path or '/'
    low = path.lower()
    if store == 'easycosmetic':
        if not low.endswith('.aspx'):
            return None
        if any(x in low for x in ('/suche', '/service', '/kontakt', '/impressum', '/datenschutz', '/agb', '/versand', '/zahlung', '/marken', '/alle-marken', '/faq/')):
            return None
        return absolute
    if store == 'deloox':
        if re.search(r'/(?:product|produit|producto|prodotto)/\d+(?:/|$)', low, re.I):
            return absolute
        if low.endswith('.html') and not re.search(r'/(?:category|categorie|categoria|catégorie|chercher|search|sitemap|brand|marque|marca|login|account|cart|checkout)(?:/|$)', low, re.I):
            return absolute
        return None
    return absolute if _looks_product(absolute) else None


def _html_listing_url(store, raw_url, base_url, label=''):
    if not raw_url:
        return None
    absolute = urllib.parse.urljoin(base_url, raw_url).split('#', 1)[0]
    p = urllib.parse.urlparse(absolute)
    allowed_hosts = {urllib.parse.urlparse(x).netloc.lower() for x in _discovery_bases(store)}
    if p.scheme not in ('http', 'https') or p.netloc.lower() not in allowed_hosts:
        return None
    path = p.path.lower()
    text = norm(f'{path} {p.query} {label}')
    if any(x in path for x in ('/login', '/account', '/cart', '/checkout', '/service', '/kontakt', '/impressum', '/datenschutz', '/agb', '/versand', '/zahlung', '/faq/')):
        return None
    if path.endswith(('.jpg','.jpeg','.png','.gif','.svg','.webp','.pdf','.css','.js')):
        return None
    if store == 'easycosmetic':
        # Brand/category pages are commonly one or two path components; the
        # explicit perfume/brand roots are the important catalog surfaces.
        if path.endswith('.aspx'):
            return None
        if any(k in text for k in ('page ', 'seite ', 'offset ', 'parfum', 'marken', 'brand', 'category', 'kategorie')):
            return absolute
        parts=[x for x in path.split('/') if x]
        if 1 <= len(parts) <= 2:
            return absolute
        return None
    if store == 'deloox':
        if re.search(r'/(?:category|categorie|categoria|catégorie|brand|marque|marca|parfum|perfume|fragrance|geur)(?:/|$)', path, re.I):
            return absolute
        if re.search(r'(?:page|pagina|p=|offset|start)=', p.query, re.I):
            return absolute
        parts=[x for x in path.split('/') if x]
        if 1 <= len(parts) <= 3 and not path.endswith('.html'):
            return absolute
        return None
    return None


def _browser_fetch_html(url, timeout_ms=25000):
    """Browser fallback for storefronts that stall normal HTTP clients."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return None, f'PLAYWRIGHT_UNAVAILABLE:{type(exc).__name__}:{exc}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
                    locale='de-DE',
                )
                page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)
                html = page.content()
                final = page.url
                if not html:
                    return None, 'BROWSER_EMPTY_BODY'
                return (final, html.encode('utf-8', 'ignore')), None
            finally:
                browser.close()
    except Exception as exc:
        return None, f'BROWSER_{type(exc).__name__}:{exc}'


def _fetch_html_page(store, url):
    try:
        resp = _http_fetch(url, timeout=HTTP_TIMEOUT)
        if resp['status'] < 400 and resp['data']:
            data = resp['data']
            ctype = (resp.get('content_type') or '').lower()
            if 'html' in ctype or re.search(br'<(?:!doctype\s+html|html|body)\b', data[:2000], re.I):
                return url, resp['url'], data, None
            http_error = f'NON_HTML;status={resp["status"]};type={ctype or "?"};bytes={len(data)}'
        else:
            http_error = _diagnostic(resp, url)
    except Exception as exc:
        http_error = f'{type(exc).__name__}:{exc}'

    if store == 'easycosmetic':
        browser_result, browser_error = _browser_fetch_html(url)
        if browser_result:
            final, data = browser_result
            return url, final, data, None
        return url, url, None, f'HTTP={http_error};{browser_error}'
    return url, url, None, http_error


def _discover_html_catalog(store, seeds, deadline=None):
    queue=[]
    queued=set()
    visited=set()
    product_urls={}
    errors=[]
    successes=0

    def add(url, depth):
        if not url or len(queued) >= HTML_MAX_PAGES * 2:
            return
        key=url.split('#',1)[0]
        if key not in queued and key not in visited and depth <= HTML_MAX_DEPTH:
            queued.add(key); queue.append((key,depth))

    for seed in seeds:
        add(seed,0)

    while queue and len(visited) < HTML_MAX_PAGES and (deadline is None or time.time() < deadline):
        batch=[]
        while queue and len(batch)<HTML_WORKERS and len(visited)+len(batch)<HTML_MAX_PAGES:
            item=queue.pop(0)
            if item[0] in visited: continue
            visited.add(item[0]); batch.append(item)
        if not batch: continue
        with ThreadPoolExecutor(max_workers=min(HTML_WORKERS,len(batch))) as pool:
            futures={pool.submit(_fetch_html_page,store,u):(u,d) for u,d in batch}
            for f in as_completed(futures):
                requested,depth=futures[f]
                try: _requested,final,data,error=f.result()
                except Exception as exc:
                    errors.append(f'{requested} -> {type(exc).__name__}:{exc}'); continue
                if error:
                    errors.append(f'{requested} -> {error}'); continue
                successes+=1
                soup=BeautifulSoup(data,'html.parser')
                # Product URLs are collected directly from links and common
                # data attributes. No product name/brand/price is embedded.
                for a in soup.find_all('a',href=True):
                    href=a.get('href'); label=a.get_text(' ',strip=True)
                    product=_html_product_url(store,href,final or requested)
                    if product:
                        product_urls[product]=''
                        continue
                    listing=_html_listing_url(store,href,final or requested,label)
                    if listing:
                        add(listing,depth+1)
                for node in soup.find_all(True):
                    for attr in ('data-url','data-href','data-link','data-product-url','data-product-link','data-target'):
                        raw=node.get(attr)
                        if not raw: continue
                        product=_html_product_url(store,raw,final or requested)
                        if product: product_urls[product]=''; continue
                        listing=_html_listing_url(store,raw,final or requested,node.get_text(' ',strip=True)[:300])
                        if listing: add(listing,depth+1)

    return {
        'product_urls':product_urls,
        'visited':len(visited),
        'successes':successes,
        'errors':errors[:20],
    }


def _set_sync_state(store, status, started_at=None, finished_at=None, discovered_count=0, fetched_count=0, error=None):
    conn = db()
    now = time.time()
    conn.execute("""INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
       VALUES(?,?,?,?,?,?,?)
       ON CONFLICT(store) DO UPDATE SET status=excluded.status,
       started_at=excluded.started_at,finished_at=excluded.finished_at,
       discovered_count=excluded.discovered_count,fetched_count=excluded.fetched_count,
       error=excluded.error""",
       (store, status, started_at if started_at is not None else now, finished_at,
        discovered_count, fetched_count, error))
    conn.commit(); conn.close()


def discover_store(store):
    """Build/update one persistent URL catalog with durable progress state."""
    started_at=time.time()
    # Persist state BEFORE network work so a slow/failing store is never falsely NOT_SYNCED.
    _set_sync_state(store, 'DISCOVERY_RUNNING', started_at=started_at, error='discovery_started')
    roots,robots_diagnostics=_seed_sitemaps(store)
    queue=[(url,0) for url in roots]
    queued=set(roots); visited=set(); product_urls={}; sitemap_errors=[]
    sitemap_successes=0; sitemap_url_entries=0

    while queue and len(visited)<MAX_SITEMAPS_PER_STORE and len(product_urls)<MAX_TOTAL_DISCOVERED_URLS and (time.time()-started_at)<DISCOVERY_HARD_TIMEOUT:
        batch=[]
        while queue and len(batch)<SYNC_WORKERS*4:
            sm,depth=queue.pop(0)
            if sm in visited: continue
            visited.add(sm); batch.append((sm,depth))
        if not batch: continue
        with ThreadPoolExecutor(max_workers=min(SYNC_WORKERS,len(batch))) as pool:
            futures={pool.submit(_fetch_sitemap,store,sm):(sm,depth) for sm,depth in batch}
            for f in as_completed(futures):
                sm,depth=futures[f]
                try: _source,final,entries,error=f.result()
                except Exception as exc:
                    final,entries=sm,[]; error=f'EXCEPTION:{type(exc).__name__}:{exc}'
                if error:
                    sitemap_errors.append(f'{sm} -> {error}'); continue
                sitemap_successes+=1; sitemap_url_entries+=len(entries)
                for kind,raw_url,lastmod in entries:
                    absolute=urllib.parse.urljoin(final or sm,raw_url.strip()) if raw_url else ''
                    if kind=='sitemap':
                        if depth+1<=MAX_SITEMAP_DEPTH and absolute not in queued:
                            queued.add(absolute); queue.append((absolute,depth+1))
                    elif _looks_product(absolute):
                        product_urls[absolute]=lastmod or ''
                        if len(product_urls)>=MAX_TOTAL_DISCOVERED_URLS: break

    fallback=None
    # Critical: zero sitemap URLs is not a NOT_FOUND condition. Use the
    # retailer's public catalog/navigation surfaces before declaring empty.
    if not product_urls and store in HTML_DISCOVERY_SEEDS:
        fallback=_discover_html_catalog(store,HTML_DISCOVERY_SEEDS[store], started_at + DISCOVERY_HARD_TIMEOUT)
        product_urls.update(fallback['product_urls'])

    diagnostics={
        'visited':len(visited),
        'successes':sitemap_successes,
        'entries':sitemap_url_entries,
        'errors':len(sitemap_errors),
        'timed_out': (time.time()-started_at) >= DISCOVERY_HARD_TIMEOUT,
    }
    # Zero successful catalog-page fetches means access/discovery failure,
    # not an empty retailer catalog. Never report EMPTY in that situation.
    if not product_urls and fallback is not None and fallback['successes'] == 0 and fallback['errors']:
        now = time.time()
        detail = 'catalog_access_failed; ' + ' | '.join(fallback['errors'][:8])
        conn = db()
        conn.execute(
            '''INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(store) DO UPDATE SET status=excluded.status,
               started_at=excluded.started_at,finished_at=excluded.finished_at,
               discovered_count=excluded.discovered_count,error=excluded.error''',
            (store, 'DISCOVERY_ERROR', started_at, now, 0, 0, detail),
        )
        conn.commit(); conn.close()
        status,count,error='DISCOVERY_ERROR',0,detail
    else:
        status,count,error=_save_discovery(store,product_urls,started_at,diagnostics)

    details=[]
    if sitemap_errors: details.append('sitemap_warnings='+' | '.join(sitemap_errors[:8]))
    if fallback is not None:
        details.append(f'html_fallback=visited:{fallback["visited"]};successes:{fallback["successes"]};products:{len(fallback["product_urls"])}')
        if fallback['errors']: details.append('html_errors='+' | '.join(fallback['errors'][:4]))
    final_error=' | '.join(details) if details else error
    conn=db()
    conn.execute('UPDATE sync_state SET error=? WHERE store=?',(final_error,store))
    conn.commit(); conn.close()

    return {
        'count':count,'status':status,'visited_sitemaps':len(visited),
        'sitemap_successes':sitemap_successes,'xml_entries':sitemap_url_entries,
        'robots':robots_diagnostics[:8],'errors':sitemap_errors[:12],
        'html_fallback':fallback,
    }


def _jsonld(soup):
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
                continue
            if not isinstance(x, dict):
                continue
            typ = x.get('@type')
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == 'product' for t in types):
                products.append(x)
            for v in x.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return products


def _num(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except Exception:
        pass
    s = re.sub(r'[^0-9,.\-]', '', str(v))
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def _first_offer(p):
    offers = p.get('offers') if isinstance(p, dict) else None
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for o in offers:
            if isinstance(o, dict) and (_num(o.get('price')) is not None or o.get('availability')):
                return o
    return {}


def parse_product(store, url, data):
    soup = BeautifulSoup(data, 'html.parser')
    h1 = soup.find('h1')
    h1text = h1.get_text(' ', strip=True) if h1 else ''
    products = _jsonld(soup)
    p = products[0] if products else {}
    name = str(p.get('name') or h1text or '').strip()
    if not name:
        return None
    brand = p.get('brand')
    if isinstance(brand, dict):
        brand = brand.get('name')
    offer = _first_offer(p)
    price = _num(offer.get('price'))
    currency = str(offer.get('priceCurrency') or 'EUR')
    availability = str(offer.get('availability') or '').lower()
    if 'instock' in availability or 'limitedavailability' in availability or 'onlineonly' in availability:
        availability = 'in_stock'
    elif any(x in availability for x in ('outofstock', 'soldout', 'discontinued')):
        availability = 'out_of_stock'
    elif 'preorder' in availability:
        availability = 'preorder'
    else:
        availability = 'unknown'
    image = p.get('image')
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get('url') or image.get('contentUrl')
    return {
        'store': STORE_LABELS[store],
        'store_key': store,
        'url': url,
        'name': name,
        'brand': str(brand or '').strip(),
        'image': image,
        'sku': str(p.get('sku') or '').strip(),
        'gtin': str(p.get('gtin13') or p.get('gtin12') or p.get('gtin14') or p.get('gtin') or '').strip(),
        'mpn': str(p.get('mpn') or '').strip(),
        'price_num': price,
        'price': price,
        'currency': currency,
        'availability': availability,
        'available': True if availability == 'in_stock' else False if availability == 'out_of_stock' else None,
        'fetched_at': time.time(),
    }


def _secondary_store_parser(store, final_url, original_url):
    """Use an existing store parser only as a product-page parser fallback."""
    try:
        module = importlib.import_module(f'scrapers.{store}.scraper')
        parser = getattr(module, 'extract_product_page', None)
        if not callable(parser):
            return None
        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})
        try:
            parsed = parser(session, final_url, url_slug(final_url))
        finally:
            session.close()
        if not isinstance(parsed, dict):
            return None

        identity = parsed.get('identity') or {}
        def identity_value(key):
            value = identity.get(key)
            if isinstance(value, dict):
                return value.get('value')
            return value

        offer = parsed.get('offer') or {}
        price = parsed.get('price_num')
        if price is None:
            price = offer.get('price')
        return {
            'store': STORE_LABELS[store],
            'store_key': store,
            'url': parsed.get('url') or final_url or original_url,
            'name': parsed.get('name') or parsed.get('title') or '',
            'brand': parsed.get('brand') or '',
            'image': parsed.get('image') or (parsed.get('source') or {}).get('image'),
            'sku': parsed.get('sku') or identity_value('sku') or '',
            'gtin': parsed.get('gtin') or identity_value('gtin') or '',
            'mpn': parsed.get('mpn') or identity_value('mpn') or '',
            'price_num': price,
            'price': price,
            'currency': parsed.get('currency') or offer.get('currency') or 'EUR',
            'availability': parsed.get('availability') or offer.get('availability') or 'unknown',
            'available': parsed.get('available'),
            'fetched_at': time.time(),
        }
    except Exception:
        return None


def refresh_url(store, url):
    try:
        status, final, data = http_get(url, timeout=REFRESH_TIMEOUT)
        if status >= 400:
            raise RuntimeError(f'HTTP {status}')

        item = parse_product(store, final, data)
        if not item:
            item = _secondary_store_parser(store, final, url)
        if not item or not item.get('name'):
            raise RuntimeError('product_parser_not_found')

        conn = db()
        conn.execute(
            '''INSERT INTO store_products(
                store,url,name,brand,image,sku,gtin,mpn,size_ml,concentration,gender,
                price,currency,availability,fetched_at,fetch_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(store,url) DO UPDATE SET
                name=excluded.name,brand=excluded.brand,image=excluded.image,
                sku=excluded.sku,gtin=excluded.gtin,mpn=excluded.mpn,
                price=excluded.price,currency=excluded.currency,
                availability=excluded.availability,fetched_at=excluded.fetched_at,
                fetch_status=excluded.fetch_status''',
            (
                store, url, item.get('name'), item.get('brand'), item.get('image'),
                item.get('sku'), item.get('gtin'), item.get('mpn'), None, None, None,
                item.get('price_num'), item.get('currency'), item.get('availability'),
                item.get('fetched_at'), 'OK',
            ),
        )
        conn.commit()
        conn.close()
        return item
    except Exception as exc:
        conn = db()
        conn.execute(
            '''INSERT INTO store_products(store,url,fetched_at,fetch_status)
               VALUES(?,?,?,?)
               ON CONFLICT(store,url) DO UPDATE SET
               fetched_at=excluded.fetched_at,fetch_status=excluded.fetch_status''',
            (store, url, time.time(), 'ERROR:' + type(exc).__name__),
        )
        conn.commit()
        conn.close()
        return None


def search_local(query, per_store=12):
    ts = tokens(query)
    if not ts:
        return []

    conn = db()
    rows = []
    for store in STORES:
        candidates = conn.execute(
            'SELECT url,slug,lastmod FROM store_urls WHERE store=? AND active=1',
            (store,),
        ).fetchall()
        scored = []
        for r in candidates:
            s = r['slug']
            score = sum(1 for t in ts if t in s)
            if score == len(ts):
                score += 10
            if score >= len(ts):
                scored.append((score, r['url']))
        scored.sort(key=lambda x: (-x[0], x[1]))
        for _, url in scored[:per_store]:
            row = conn.execute(
                'SELECT * FROM store_products WHERE store=? AND url=?',
                (store, url),
            ).fetchone()
            if row:
                item = dict(row)
                item['price_num'] = item.get('price')
                item['store'] = STORE_LABELS[store]
                item['store_key'] = store
                rows.append(item)
            else:
                rows.append({
                    'store': STORE_LABELS[store],
                    'store_key': store,
                    'url': url,
                    'name': url_slug(url),
                    '_needs_refresh': True,
                })
    conn.close()
    return rows


def refresh_candidates(rows):
    jobs = [(r['store_key'], r['url']) for r in rows if r.get('_needs_refresh')]
    if not jobs:
        return []
    out = []
    with ThreadPoolExecutor(max_workers=min(REFRESH_WORKERS, len(jobs))) as pool:
        futures = [pool.submit(refresh_url, store, url) for store, url in jobs]
        for future in as_completed(futures):
            try:
                item = future.result()
                if item:
                    out.append(item)
            except Exception:
                pass
    return out


def sync_all():
    results = {}
    # Persist a state for all stores before workers start. A slow store is
    # immediately visible as queued/running instead of falsely NOT_SYNCED.
    now = time.time()
    conn = db()
    with conn:
        for store in STORES:
            conn.execute("""INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(store) DO UPDATE SET status=excluded.status,
               started_at=excluded.started_at,finished_at=excluded.finished_at,
               discovered_count=excluded.discovered_count,fetched_count=excluded.fetched_count,
               error=excluded.error""",
               (store, 'DISCOVERY_QUEUED', now, None, 0, 0, 'waiting_for_discovery_worker'))
    conn.close()
    with ThreadPoolExecutor(max_workers=min(SYNC_WORKERS, len(STORES))) as pool:
        futures = {pool.submit(discover_store, store): store for store in STORES}
        for future in as_completed(futures):
            store = futures[future]
            try:
                results[store] = future.result()
            except Exception as exc:
                now = time.time()
                results[store] = {
                    'count': 0,
                    'status': 'DISCOVERY_ERROR',
                    'error': f'{type(exc).__name__}: {exc}',
                }
                conn = db()
                conn.execute(
                    '''INSERT INTO sync_state(store,status,started_at,finished_at,discovered_count,fetched_count,error)
                       VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(store) DO UPDATE SET status=excluded.status,
                       finished_at=excluded.finished_at,error=excluded.error''',
                    (store, 'DISCOVERY_ERROR', now, now, 0, 0, f'{type(exc).__name__}: {exc}'),
                )
                conn.commit()
                conn.close()
    return results


def store_status():
    conn = db()
    now = time.time()
    out = {}
    for store in STORES:
        r = conn.execute('SELECT * FROM sync_state WHERE store=?', (store,)).fetchone()
        count = conn.execute(
            'SELECT COUNT(*) c FROM store_urls WHERE store=? AND active=1', (store,)
        ).fetchone()['c']
        fetched = conn.execute(
            'SELECT COUNT(*) c FROM store_products WHERE store=? AND fetch_status="OK"', (store,)
        ).fetchone()['c']
        derived_status = (
            r['status'] if r else
            ('READY' if fetched else 'INDEXED' if count else 'NOT_SYNCED')
        )
        out[store] = {
            'status': derived_status,
            'indexed_urls': count,
            'fetched_products': fetched,
            'finished_at': r['finished_at'] if r else None,
            'age_sec': (now - r['finished_at']) if r and r['finished_at'] else None,
            'error': r['error'] if r else None,
        }
    conn.close()
    return out


if __name__ == '__main__':
    print(json.dumps(sync_all(), indent=2, ensure_ascii=False))

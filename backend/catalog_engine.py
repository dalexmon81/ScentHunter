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
import html
import heapq
import importlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
import os
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('SCENTHUNTER_CATALOG_DB', str(BASE_DIR / 'store_catalog.sqlite3'))).expanduser()

STORES = {
    'bplatz': 'https://en.bplatz.de',
    'parfumcity': 'https://www.parfumcity.nl',
    'parfumzentrum': 'https://www.parfum-zentrum.de',
    'perfumemarket': 'https://www.perfumemarket.nl',
    'sabina': 'https://www.sabina.com',
    'orioudh': 'https://orioudh.com',
    'easycosmetic': 'https://www.easycosmetic.de',
    'deloox': 'https://www.deloox.be',
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
        'https://www.deloox.be',
        'https://www.deloox.com',
    ),
}

USER_AGENT = 'ScentHunterBot/7.0 (+price-comparison; catalog indexing)'
EASY_COSMETIC_USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/131.0.0.0 Safari/537.36')
EASY_COSMETIC_HEADERS = {
    'User-Agent': EASY_COSMETIC_USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1',
}
DELOOX_USER_AGENT = (
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)
DELOOX_HEADERS = {
    'User-Agent': DELOOX_USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-GB,en;q=0.9',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1',
}
HTTP_TIMEOUT = 15
SITEMAP_TIMEOUT = 20
REFRESH_TIMEOUT = 10

SYNC_WORKERS = 8
REFRESH_WORKERS = 2

# Persistent hydration queue configuration.
HYDRATION_WORKERS = 8
HYDRATION_LEASE_SECONDS = 120.0
HYDRATION_MAX_ATTEMPTS = 8
HYDRATION_BACKOFF_SECONDS = (60.0, 300.0, 1800.0, 7200.0, 21600.0, 86400.0)
HYDRATION_RETRY_JITTER = 0.20

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
    r'categories|collection|collections|brand|brands|marca|marque|sitemap|'
    r'login|account|cart|checkout|blog|news|tag|tags|help|faq|pages|'
    r'privacy|privacy-policy|terms|terms-of-service|refund|returns|shipping|'
    r'contact|about|legal|policies)(?:/|$)',
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
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host in {'easycosmetic.de', 'www.easycosmetic.de'}:
        # Easycosmetic serves the public storefront to normal browser clients
        # but can stall requests carrying an identifying bot user-agent.
        # Use the same browser-class headers as the production Easycosmetic
        # scraper. This is transport only; discovery remains generic.
        response = _session().get(url, headers=EASY_COSMETIC_HEADERS, timeout=timeout, allow_redirects=True)
    elif host in {
        'deloox.be', 'www.deloox.be',
        'deloox.com', 'www.deloox.com',
        'deloox.nl', 'www.deloox.nl',
    }:
        # Deloox exposes its catalog graph to browser-class requests. Keep
        # catalog discovery generic, but use the same browser request profile
        # as the production Deloox scraper instead of ScentHunterBot/7.0.
        response = _session().get(url, headers=DELOOX_HEADERS, timeout=timeout, allow_redirects=True)
    else:
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


_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False

# search_local() is called on every user search. Rebuilding the token/posting
# index from every active store URL on every call is unnecessarily expensive,
# especially while the background hydration workers are parsing product pages.
#
# Discovery changes invalidate/rebuild the affected store index. Hydration does
# NOT change the discovery signature: when one product page is hydrated, the
# existing in-memory index is updated only for that URL.
_LOCAL_SEARCH_INDEX_CACHE = {}
_LOCAL_SEARCH_INDEX_LOCK = threading.Lock()


def _update_local_search_index_product(store, url, slug=None, name=None, brand=None):
    """Update one hydrated product inside an already-built local search index.

    Hydration runs in background worker threads while user searches can read the
    same index. The cache is therefore mutated only under the same lock used by
    search_local(). If no index exists yet, there is nothing to update; the next
    search will build it from the persistent catalog.
    """
    with _LOCAL_SEARCH_INDEX_LOCK:
        cached = _LOCAL_SEARCH_INDEX_CACHE.get(store)
        if not cached:
            return

        postings = cached['postings']
        url_tokens = cached['url_tokens']

        old_tokens = url_tokens.pop(url, set())
        for token in old_tokens:
            bucket = postings.get(token)
            if not bucket:
                continue
            bucket.discard(url)
            if not bucket:
                postings.pop(token, None)

        search_text = ' '.join(
            str(value or '') for value in (slug, name, brand)
        )
        new_tokens = set(norm(search_text).split())
        url_tokens[url] = new_tokens
        for token in new_tokens:
            postings.setdefault(token, set()).add(url)


def _remove_local_search_index_url(store, url):
    """Remove one URL from an already-built local search index."""
    with _LOCAL_SEARCH_INDEX_LOCK:
        cached = _LOCAL_SEARCH_INDEX_CACHE.get(store)
        if not cached:
            return

        postings = cached['postings']
        url_tokens = cached['url_tokens']
        old_tokens = url_tokens.pop(url, set())

        for token in old_tokens:
            bucket = postings.get(token)
            if not bucket:
                continue
            bucket.discard(url)
            if not bucket:
                postings.pop(token, None)


def _ensure_schema(conn):
    """Create/migrate the catalog schema once per process.

    Search and hydration connections share the same SQLite file. Running
    CREATE TABLE/INDEX and switching journal mode on every connection creates
    avoidable schema-lock contention and can make /search appear to hang while
    background hydration is writing. Schema setup is therefore serialized and
    executed only once after process start.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute("""CREATE TABLE IF NOT EXISTS store_urls(
            store TEXT NOT NULL, url TEXT NOT NULL, slug TEXT NOT NULL,
            lastmod TEXT, discovered_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(store,url))""")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_store_urls_slug ON store_urls(store,slug)')
        conn.execute("""CREATE TABLE IF NOT EXISTS store_products(
            store TEXT NOT NULL, url TEXT NOT NULL, name TEXT, brand TEXT, image TEXT,
            sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL, concentration TEXT, gender TEXT,
            price REAL, currency TEXT, availability TEXT, fetched_at REAL, fetch_status TEXT,
            PRIMARY KEY(store,url))""")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_store_products_store_name ON store_products(store,name)')
        conn.execute("""CREATE TABLE IF NOT EXISTS sync_state(
            store TEXT PRIMARY KEY, status TEXT, started_at REAL, finished_at REAL,
            discovered_count INTEGER DEFAULT 0, fetched_count INTEGER DEFAULT 0, error TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hydration_queue(
            store TEXT NOT NULL,
            url TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL DEFAULT 0,
            leased_until REAL,
            lease_token TEXT,
            first_seen_at REAL NOT NULL,
            last_started_at REAL,
            last_finished_at REAL,
            last_error TEXT,
            last_http_status INTEGER,
            PRIMARY KEY(store,url)
        )""")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hydration_ready ON hydration_queue(state,available_at,store)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hydration_lease ON hydration_queue(state,leased_until)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hydration_store_state ON hydration_queue(store,state)')
        conn.execute("""CREATE TABLE IF NOT EXISTS hydration_scheduler(
            id INTEGER PRIMARY KEY CHECK(id=1),
            last_store_index INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute('INSERT OR IGNORE INTO hydration_scheduler(id,last_store_index) VALUES(1,0)')
        conn.commit()
        _SCHEMA_READY = True


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    _ensure_schema(conn)
    conn.execute('PRAGMA synchronous=NORMAL')
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
    path_lower = urllib.parse.unquote(p.path).lower().rstrip('/')
    if path_lower in ('/robots.txt', '/humans.txt', '/ads.txt', '/security.txt', '/llms.txt', '/agents.md'):
        return False
    if NON_PRODUCT_PATH.search(p.path):
        return False
    # Sabina's /l/ and /s/ paths are landing/search/navigation pages, not
    # products. They can look like products to the generic slug heuristic
    # because their slugs contain multiple words, so exclude them here while
    # keeping the generic heuristic unchanged for the other stores.
    if re.match(r'^/[a-z]{2}/(?:l|s)(?:/|$)', p.path, re.I):
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
                conn.execute(
                    '''INSERT INTO hydration_queue(
                           store,url,state,attempts,available_at,first_seen_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                           state=CASE
                               WHEN hydration_queue.state='DONE' THEN 'DONE'
                               WHEN hydration_queue.state='PROCESSING'
                                    AND hydration_queue.leased_until > ? THEN 'PROCESSING'
                               ELSE hydration_queue.state
                           END''',
                    (store, url, 'PENDING', 0, now, now, now),
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
        'https://www.easycosmetic.de/damenparfum',
        'https://www.easycosmetic.de/herrenparfum',
        'https://www.easycosmetic.de/unisex-parfum',
        'https://www.easycosmetic.de/luxusparfum',
        'https://www.easycosmetic.de/neuheiten',
    ),
    'deloox': (
        # Broad official catalog surfaces. Both public Deloox hosts are
        # included because the catalog graph is split across storefronts.
        'https://www.deloox.be/',
        'https://www.deloox.be/en/',
        'https://www.deloox.com/',
        'https://www.deloox.com/en/',
        'https://www.deloox.be/en/category/1103659/fragrances.html',
        'https://www.deloox.com/en/category/1103659/fragrances.html',
        # Current Deloox fragrance-category surfaces used by the public
        # storefront. These are generic catalog roots, not product/query URLs.
        'https://www.deloox.be/categorie/1075744/eau-de-toilette-homme.html',
        'https://www.deloox.com/categorie/1075744/eau-de-toilette-homme.html',
        'https://www.deloox.be/categorie/1075743/eau-de-parfum-femme.html',
        'https://www.deloox.com/categorie/1075743/eau-de-parfum-femme.html',
        'https://www.deloox.be/en/category/1063858/brands.html',
        'https://www.deloox.com/en/category/1063858/brands.html',
        'https://www.deloox.be/en/category/1000003/fragrances.html',
        'https://www.deloox.com/en/category/1000003/fragrances.html',
        'https://www.deloox.be/en/category/1000054/mens-fragrances.html',
        'https://www.deloox.com/en/category/1000054/mens-fragrances.html',
        'https://www.deloox.be/en/category/1075750/mens-perfume.html',
        'https://www.deloox.com/en/category/1075750/mens-perfume.html',
        'https://www.deloox.be/en/category/1075660/womens-perfume.html',
        'https://www.deloox.com/en/category/1075660/womens-perfume.html',
        'https://www.deloox.be/category/1063858/brands.html',
        'https://www.deloox.com/category/1063858/brands.html',
        'https://www.deloox.be/category/1000003/fragrances.html',
        'https://www.deloox.com/category/1000003/fragrances.html',
        'https://www.deloox.be/category/1000054/mens-fragrances.html',
        'https://www.deloox.com/category/1000054/mens-fragrances.html',
        'https://www.deloox.be/category/1075750/mens-perfume.html',
        'https://www.deloox.com/category/1075750/mens-perfume.html',
        'https://www.deloox.be/category/1075660/womens-perfume.html',
        'https://www.deloox.com/category/1075660/womens-perfume.html',
    ),
    'sabina': (
        'https://www.sabina.com/it/',
        'https://www.sabina.com/it/6-profumi-di-donna',
        'https://www.sabina.com/it/7-profumi-da-uomo',
        'https://www.sabina.com/it/30-profumi-donna',
        'https://www.sabina.com/it/31-profumi-uomo',
        'https://www.sabina.com/it/890-profumeria-di-nicchia',
        'https://www.sabina.com/it/s/48/profumi-donna-profumi-uomo',
        # Broad Arabic-fragrance landing surface exposed by Sabina's own
        # sitemap. It is a catalog/navigation surface, not a product query.
        'https://www.sabina.com/it/l/profumi-arabi',
    ),
}
# HTML discovery is background catalog work, not request-time search. The old
# 300-page/5-level ceiling could stop before the retailer's real catalog
# pagination/navigation surface was exhausted.
HTML_MAX_PAGES = 800
HTML_MAX_DEPTH = 8
HTML_WORKERS = 12
DISCOVERY_HARD_TIMEOUT = 300

# Sitemap discovery gets its own short budget. Some retailers expose broken
# or slow sitemap roots while their public HTML catalog is available. The
# generic HTML fallback must always receive a real execution window.
SITEMAP_DISCOVERY_BUDGET = 45

# A sitemap can be technically valid yet represent only a tiny slice of the
# retailer catalog. When a store has an HTML catalog surface, supplement very
# small sitemap discoveries instead of treating them as complete.
HTML_FALLBACK_SITEMAP_PRODUCT_THRESHOLD = 100


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
    if store == 'sabina':
        # Sabina product pages use a numeric product id followed by a slug and
        # end in .html. Listing/navigation pages use different URL shapes
        # such as /it/31-profumi-uomo or /it/l/.... This is URL-shape
        # classification only; no perfume/product name is embedded here.
        if re.search(r'/\d+-[^/]+\.html$', low, re.I):
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
    if any(x in path for x in (
        '/login', '/account', '/cart', '/checkout', '/service', '/kontakt',
        '/impressum', '/datenschutz', '/agb', '/versand', '/zahlung', '/faq/',
        '/wishlist', '/customer-service', '/shopping-cart', '/my-account',
        '/order/', '/customer/', '/help/',
    )):
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
        # The Deloox homepage is the root of the catalog graph.
        if path in ('', '/'):
            return absolute
        if re.search(r'/(?:category|categorie|categoria|catégorie|brand|marque|marca|parfum|perfume|fragrance|geur)(?:/|$)', path, re.I):
            return absolute
        if re.search(r'(?:page|pagina|p=|offset|start)=', p.query, re.I):
            return absolute
        # Some retailer filters are query-only links on an existing catalog
        # path. Treat generic filter/navigation keys as catalog surfaces.
        if re.search(
            r'(?:^|&)(?:brand|brands|manufacturer|manufacturers|category|categories|filter|filters|facet|facets|attribute|attributes|gender|collection)=',
            p.query, re.I,
        ):
            return absolute
        parts=[x for x in path.split('/') if x]
        if 1 <= len(parts) <= 3 and not path.endswith('.html'):
            return absolute
        return None
    if store == 'sabina':
        # Sabina catalog/navigation pages are crawlable without a query
        # endpoint. Product pages are excluded here because _html_product_url
        # handles their numeric-id .html shape.
        if path.endswith('.html'):
            return None
        if re.search(r'(?:page|pagina|p=|page=|offset|start)=', p.query, re.I):
            return absolute
        if re.search(r'/(?:profumi|perfumes|parfums|l/|s/)', path, re.I):
            return absolute
        parts=[x for x in path.split('/') if x]
        if 1 <= len(parts) <= 3:
            return absolute
        return None
    return None


def _browser_fetch_html(url, timeout_ms=15000):
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



def _html_discovery_priority(store, url, depth, source=''):
    """Return a generic crawl priority; lower values are visited first.

    The HTML catalog fallback can discover thousands of links from a single
    storefront page. FIFO traversal lets utility pages and unrelated site
    surfaces consume the queue before the retailer's product/category graph is
    explored. This score only uses URL structure, never the requested product
    name, brand, price, or a store-specific product exception.
    """
    p = urllib.parse.urlparse(url)
    path = (p.path or '/').lower()
    text = norm(f'{path} {p.query}')

    # Catalog index pages are high-value navigation surfaces because they
    # expose the next level of category/brand pages. This is structural only:
    # no specific retailer brand, product name, product id, or user query is used.
    if re.search(r'/(?:brands?|marques?|marcas|marken)(?:\.html)?$', path, re.I):
        score = 0
    # Prefer actual fragrance catalog surfaces before unrelated site sections.
    # This is URL-structure based only: no product name, brand name, product
    # id, or user query is used.
    elif any(term in text for term in ('fragrance', 'fragrances', 'perfume', 'parfum', 'parfums', 'profumi', 'perfumes')):
        score = 1
    elif re.search(r'/(?:category|categorie|categoria|catégorie|categories)(?:/|$)', path, re.I):
        score = 2
    elif re.search(r'/(?:brand|brands|marque|marca)(?:/|$)', path, re.I):
        score = 3
    elif re.search(r'/(?:collection|collections)(?:/|$)', path, re.I):
        score = 3
    elif re.search(r'(?:page|pagina|offset|start|p=)', p.query, re.I):
        score = 4
    elif path in ('/', '') or path.rstrip('/') in ('/en', '/it', '/de', '/fr', '/nl', '/es'):
        score = 8
    else:
        score = 6

    # Deeper pages are still valid, but breadth-first behavior should only
    # break ties between otherwise equivalent catalog surfaces.
    return (score, depth)

def _discover_deloox_catalog(seeds, deadline=None):
    """Discover Deloox products through its public category graph.

    Deloox exposes a large amount of catalog navigation in category pages,
    while sitemap endpoints are frequently unavailable. The crawler therefore
    traverses the retailer-owned catalog graph directly. Fetches are performed
    in bounded parallel batches so one slow/large Deloox page cannot consume
    the entire discovery deadline.

    No product name, brand name, product id, or search query is used here.
    """
    queue = []
    queued = set()
    visited = set()
    product_urls = {}
    errors = []
    sequence = 0
    max_pages = min(800, HTML_MAX_PAGES)
    max_depth = min(10, HTML_MAX_DEPTH)

    def add(url, depth, source=''):
        nonlocal sequence
        if not url or depth > max_depth or len(queued) >= max_pages * 8:
            return
        key = url.split('#', 1)[0]
        if key in queued or key in visited:
            return
        p = urllib.parse.urlparse(key)
        if p.scheme not in ('http', 'https') or p.netloc.lower() not in {urllib.parse.urlparse(x).netloc.lower() for x in _discovery_bases('deloox')}:
            return
        path = p.path.lower()
        if '/product/' in path:
            product = _html_product_url('deloox', key, key)
            if product:
                product_urls[product] = ''
            return
        listing = _html_listing_url('deloox', key, key, source)
        if not listing:
            return
        sequence += 1
        priority = _html_discovery_priority('deloox', key, depth, source)
        # _html_discovery_priority() returns only the structural
        # (score, depth) tuple. Keep that structural priority and use the
        # insertion sequence as the deterministic FIFO tie-breaker between
        # equivalent catalog branches. This preserves the fair fan-out
        # ordering without depending on a non-existent priority[2].
        heap_priority = (priority[0], priority[1], sequence)
        heapq.heappush(queue, (heap_priority, sequence, key, depth, source))
        queued.add(key)

    for seed in seeds:
        add(seed, 0, 'configured_seed')

    def _fair_catalog_links(items):
        """Interleave large navigation fan-outs by structural URL bucket.

        Deloox brand/category indexes can expose thousands of links from one
        page. Processing those links in lexical URL order can starve entire
        parts of the catalog before the page budget expires. Interleaving by
        the first alphanumeric character of the final path component preserves
        generic discovery while giving every structural branch an opportunity
        to be visited.
        """
        buckets = {}
        for item in items:
            url = item[0]
            parsed = urllib.parse.urlparse(url)
            parts = [x for x in (parsed.path or '').split('/') if x]
            key = (parts[-1] if parts else parsed.netloc).lower()
            bucket = key[0] if key and key[0].isalnum() else '#'
            buckets.setdefault(bucket, []).append(item)
        ordered = []
        for key in sorted(buckets):
            buckets[key].sort(key=lambda x: x[0])
        while buckets:
            for key in list(sorted(buckets)):
                values = buckets.get(key)
                if not values:
                    buckets.pop(key, None)
                    continue
                ordered.append(values.pop(0))
                if not values:
                    buckets.pop(key, None)
        return ordered

    def process_page(requested, depth, source, result):
        """Collect products and enqueue catalog/navigation URLs from one page."""
        _requested, final, data, error = result
        if error:
            errors.append(f'{requested} -> {error}')
            return

        soup = BeautifulSoup(data, 'html.parser')
        base = final or requested

        anchor_listings = []
        for a in soup.find_all('a', href=True):
            raw = a.get('href')
            product = _html_product_url('deloox', raw, base)
            if product:
                product_urls[product] = ''
                continue
            listing = _html_listing_url('deloox', raw, base, a.get_text(' ', strip=True))
            if listing:
                anchor_listings.append((listing, depth + 1, requested))
        for listing, next_depth, next_source in _fair_catalog_links(anchor_listings):
            add(listing, next_depth, next_source)

        for node in soup.find_all(True):
            label = node.get_text(' ', strip=True)[:300]
            for attr in (
                'value', 'data-value', 'data-filter-url', 'data-option-url',
                'data-redirect-url', 'data-url', 'data-href', 'data-link',
                'data-next-url', 'data-next', 'data-load-more-url',
                'data-pagination-url',
            ):
                raw = node.get(attr)
                if not raw:
                    continue
                product = _html_product_url('deloox', raw, base)
                if product:
                    product_urls[product] = ''
                    continue
                listing = _html_listing_url('deloox', raw, base, label)
                if listing:
                    add(listing, depth + 1, requested)

        try:
            raw_html = html.unescape(data.decode('utf-8', 'ignore'))
            raw_html = raw_html.replace('\\/', '/')
            raw_html = raw_html.replace('\\u002F', '/').replace('\\u002f', '/')
            for match in re.finditer(
                r"https?://[^\"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^\"'\s<>\\]+",
                raw_html,
                re.I,
            ):
                raw = match.group(0)
                absolute = urllib.parse.urljoin(base, raw).split('#', 1)[0]
                product = _html_product_url('deloox', absolute, base)
                if product:
                    product_urls[product] = ''
                    continue
                listing = _html_listing_url('deloox', absolute, base, 'embedded_navigation')
                if listing:
                    add(listing, depth + 1, requested)
        except Exception:
            pass

        for node in soup.find_all(['a', 'link'], href=True):
            rel = ' '.join(node.get('rel') or []).lower()
            href = node.get('href')
            if 'next' in rel or re.search(r'(?:page|pagina|offset|start|p)=', urllib.parse.urlparse(href or '').query, re.I):
                listing = _html_listing_url('deloox', href, base, 'pagination')
                if listing:
                    add(listing, depth + 1, requested)

    # Parallel batches are deliberately bounded by the same HTML worker pool
    # used by the generic crawler. The queue itself remains priority-ordered,
    # so high-value catalog surfaces are still preferred without serializing
    # the network I/O.
    while queue and len(visited) < max_pages and (deadline is None or time.time() < deadline):
        batch = []
        while queue and len(batch) < HTML_WORKERS and len(visited) + len(batch) < max_pages:
            _priority, _sequence, url, depth, source = heapq.heappop(queue)
            if url in visited:
                continue
            visited.add(url)
            batch.append((url, depth, source))
        if not batch:
            continue

        with ThreadPoolExecutor(max_workers=min(HTML_WORKERS, len(batch))) as pool:
            futures = {
                pool.submit(_fetch_html_page, 'deloox', url): (url, depth, source)
                for url, depth, source in batch
            }
            for future in as_completed(futures):
                requested, depth, source = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    errors.append(f'{requested} -> {type(exc).__name__}:{exc}')
                    continue
                process_page(requested, depth, source, result)

    return {
        'product_urls': product_urls,
        'visited': len(visited),
        'successes': len(visited) - len(errors),
        'errors': errors[:20],
    }


def _discover_html_catalog(store, seeds, deadline=None):
    queue=[]
    queued=set()
    visited=set()
    product_urls={}
    errors=[]
    successes=0
    sequence=0

    def add(url, depth, source=''):
        nonlocal sequence
        if not url or len(queue) >= HTML_MAX_PAGES * 20:
            return
        key=url.split('#',1)[0]
        if key not in queued and key not in visited and depth <= HTML_MAX_DEPTH:
            sequence += 1
            priority=_html_discovery_priority(store, key, depth, source)
            heapq.heappush(queue, (priority, sequence, key, depth, source))
            queued.add(key)

    for seed in seeds:
        add(seed,0,'configured_seed')

    while queue and len(visited) < HTML_MAX_PAGES and (deadline is None or time.time() < deadline):
        batch=[]
        while queue and len(batch)<HTML_WORKERS and len(visited)+len(batch)<HTML_MAX_PAGES:
            _priority, _sequence, url, depth, source = heapq.heappop(queue)
            if url in visited: continue
            visited.add(url); batch.append((url,depth,source))
        if not batch: continue
        with ThreadPoolExecutor(max_workers=min(HTML_WORKERS,len(batch))) as pool:
            futures={pool.submit(_fetch_html_page,store,u):(u,d,source) for u,d,source in batch}
            for f in as_completed(futures):
                requested,depth,source=futures[f]
                try: _requested,final,data,error=f.result()
                except Exception as exc:
                    errors.append(f'{requested} -> {type(exc).__name__}:{exc}'); continue
                if error:
                    errors.append(f'{requested} -> {error}'); continue
                successes+=1
                soup=BeautifulSoup(data,'html.parser')
                # Product URLs are collected directly from links and common
                # data attributes. No product name/brand/price is embedded.
                page_base=final or requested

                # Normal anchors are the primary catalog graph.
                for a in soup.find_all('a',href=True):
                    href=a.get('href'); label=a.get_text(' ',strip=True)
                    product=_html_product_url(store,href,page_base)
                    if product:
                        product_urls[product]=''
                        continue
                    listing=_html_listing_url(store,href,page_base,label)
                    if listing:
                        add(listing,depth+1,requested)

                # Many modern storefronts put pagination/load-more targets in
                # attributes instead of normal hrefs. Follow these generic
                # navigation attributes; never use the user's query here.
                navigation_attrs=(
                    'data-url','data-href','data-link','data-product-url',
                    'data-product-link','data-target','data-next-url',
                    'data-next','data-load-more-url','data-pagination-url',
                )
                for node in soup.find_all(True):
                    for attr in navigation_attrs:
                        raw=node.get(attr)
                        if not raw:
                            continue
                        product=_html_product_url(store,raw,page_base)
                        if product:
                            product_urls[product]=''
                            continue
                        listing=_html_listing_url(
                            store,raw,page_base,
                            node.get_text(' ',strip=True)[:300],
                        )
                        if listing:
                            add(listing,depth+1,requested)

                # Explicit rel=next is a standard pagination mechanism and is
                # easy to miss when it lives in <head> rather than in an <a>.
                for node in soup.find_all('link',href=True):
                    rel=' '.join(node.get('rel') or []).lower()
                    if 'next' not in rel:
                        continue
                    listing=_html_listing_url(store,node.get('href'),page_base,'next')
                    if listing:
                        add(listing,depth+1,requested)

                # Product JSON-LD is another standard storefront surface. It
                # gives us product URLs without depending on CSS/DOM layout.
                try:
                    for item in _jsonld(soup):
                        raw_url=item.get('url')
                        product=_html_product_url(store,raw_url,page_base)
                        if product:
                            product_urls[product]=''
                except Exception:
                    pass

                # Some modern retailers keep catalog navigation/filter targets
                # inside JavaScript state or JSON blobs instead of real <a>
                # elements. Deloox uses this pattern for parts of its category
                # and brand navigation. Extract only URLs belonging to the
                # retailer's own discovery hosts, then run them through the same
                # generic product/listing classifiers above. This is not a
                # product/query rule and does not depend on Liquid Brun, a brand,
                # or any other requested perfume.
                try:
                    raw_html = data.decode('utf-8', 'ignore')
                    # Deloox embeds some catalog routes in escaped JSON/JS
                    # strings (https:\/\/www... or \/category/...).
                    # Normalize only URL escaping before extracting candidates.
                    raw_html = raw_html.replace('\\/', '/')
                    host_patterns = {
                        urllib.parse.urlparse(base).netloc.lower()
                        for base in _discovery_bases(store)
                    }
                    candidates = set()
                    # Accept both absolute same-site URLs and root-relative
                    # routes. Root-relative routes are important when Deloox
                    # stores generic category/brand navigation in JS state
                    # instead of an <a href>. The normal classifiers below
                    # still decide whether each route is a product or listing.
                    for match in re.finditer(
                        r"https?://[^\"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^\"'\s<>\\]+",
                        raw_html,
                        re.I,
                    ):
                        raw = match.group(0)
                        absolute = urllib.parse.urljoin(page_base, raw).split('#', 1)[0]
                        parsed = urllib.parse.urlparse(absolute)
                        if parsed.netloc.lower() not in host_patterns:
                            continue
                        candidates.add(absolute)
                    for raw in candidates:
                        product=_html_product_url(store,raw,page_base)
                        if product:
                            product_urls[product]=''
                            continue
                        listing=_html_listing_url(store,raw,page_base,'embedded_navigation')
                        if listing:
                            add(listing,depth+1,requested)
                except Exception:
                    pass

    return {
        'product_urls':product_urls,
        'visited':len(visited),
        'successes':successes,
        'errors':errors[:20],
    }


def diagnose_html_discovery_trace(store, query='', max_pages=40, max_depth=8, max_events=300):
    """READ-ONLY funnel diagnostic for one target product.

    Stage 1: reach pages containing all query tokens.
    Stage 2: inspect only HTML nodes/attributes associated with those tokens.
    Stage 3: show the exact raw URL, normalized URL, product classifier result,
    and the precise generic URL-shape rejection reason.

    No DB writes, no production search, no hydration, no resync.
    """
    store = str(store or '').strip().lower()
    diagnostic = 'html-discovery-trace-read-only-v3-funnel'
    if store not in HTML_DISCOVERY_SEEDS:
        return {'ok': False, 'diagnostic': diagnostic, 'error': f'html_discovery_not_configured:{store}', 'store': store}

    try:
        max_pages = max(1, min(int(max_pages or 40), 40))
    except Exception:
        max_pages = 40
    try:
        max_depth = max(0, min(int(max_depth if max_depth is not None else 8), HTML_MAX_DEPTH))
    except Exception:
        max_depth = 8
    try:
        max_events = max(50, min(int(max_events or 300), 1000))
    except Exception:
        max_events = 300

    required_tokens = tokens(query)
    if not required_tokens:
        return {'ok': False, 'diagnostic': diagnostic, 'error': 'query_required', 'store': store}

    def has_tokens(value):
        value = norm(value)
        return all(t in value for t in required_tokens)

    def classify_reason(raw_url, base_url):
        """Explain _html_product_url() without changing its production logic."""
        if not raw_url:
            return {'classification': 'NOT_PRODUCT', 'reason': 'empty_url', 'normalized_url': None}
        absolute = urllib.parse.urljoin(base_url, raw_url).split('#', 1)[0]
        p = urllib.parse.urlparse(absolute)
        if p.scheme not in ('http', 'https'):
            return {'classification': 'NOT_PRODUCT', 'reason': 'invalid_scheme', 'normalized_url': absolute}
        allowed_hosts = {urllib.parse.urlparse(x).netloc.lower() for x in _discovery_bases(store)}
        if p.netloc.lower() not in allowed_hosts:
            return {'classification': 'NOT_PRODUCT', 'reason': 'host_not_allowed', 'normalized_url': absolute}
        path = p.path or '/'
        low = path.lower()
        if store == 'deloox':
            if re.search(r'/(?:product|produit|producto|prodotto)/\d+(?:/|$)', low, re.I):
                return {'classification': 'PRODUCT', 'reason': 'numeric_product_path', 'normalized_url': absolute}
            if low.endswith('.html'):
                excluded = re.search(r'/(?:category|categorie|categoria|catégorie|chercher|search|sitemap|brand|marque|marca|login|account|cart|checkout)(?:/|$)', low, re.I)
                if not excluded:
                    return {'classification': 'PRODUCT', 'reason': 'html_product_shape', 'normalized_url': absolute}
                return {'classification': 'NOT_PRODUCT', 'reason': 'excluded_listing_or_system_path', 'normalized_url': absolute}
            return {'classification': 'NOT_PRODUCT', 'reason': 'not_product_url_shape', 'normalized_url': absolute}
        product = _html_product_url(store, raw_url, base_url)
        return {'classification': 'PRODUCT' if product else 'NOT_PRODUCT',
                'reason': 'accepted_by_classifier' if product else 'classifier_rejected',
                'normalized_url': absolute}

    # We deliberately reuse the production seed/queue mechanics only to find
    # the first pages containing the complete query. Once found, the funnel
    # stops expanding the universe and inspects only target-associated nodes.
    queue, queued, visited = [], set(), set()
    sequence = 0
    query_pages = []
    page_inspections = []

    def add(url, depth, source=''):
        nonlocal sequence
        if not url:
            return False
        key = url.split('#', 1)[0]
        if key in queued or key in visited or depth > max_depth:
            return False
        if len(queued) >= max_pages * 4:
            return False
        sequence += 1
        priority = _html_discovery_priority(store, key, depth, source)
        heapq.heappush(queue, ((priority[0], priority[1], sequence), sequence, key, depth, source))
        queued.add(key)
        return True

    for seed in list(dict.fromkeys(HTML_DISCOVERY_SEEDS.get(store, ()) )):
        add(seed, 0, 'configured_seed')

    started = time.time()
    successes = 0
    errors = []

    def candidate_item(kind, raw, base_url, label='', attribute=None, context=''):
        result = classify_reason(raw, base_url)
        item = {
            'kind': kind,
            'label': label[:300],
            'attribute': attribute,
            'raw_url': raw,
            'normalized_url': result['normalized_url'],
            'classification': result['classification'],
            'reason': result['reason'],
            'context': context[:500],
        }
        if result['classification'] == 'PRODUCT' and has_tokens(result['normalized_url']):
            item['query_product_hit'] = True
        else:
            item['query_product_hit'] = False
        return item

    # We need a small amount of navigation extraction solely to reach the
    # target pages. It is not reported as a product result and is not written.
    while queue and len(visited) < max_pages and not query_pages and (time.time() - started) < 120:
        _priority, _sequence, requested, depth, source = heapq.heappop(queue)
        if requested in visited:
            continue
        visited.add(requested)
        try:
            _requested, final, data, error = _fetch_html_page(store, requested)
        except Exception as exc:
            final, data, error = requested, None, f'{type(exc).__name__}:{exc}'
        if error:
            errors.append(f'{requested} -> {error}')
            continue
        successes += 1
        page_base = final or requested
        soup = BeautifulSoup(data, 'html.parser')
        page_text = soup.get_text(' ', strip=True)
        if has_tokens(page_text):
            query_pages.append({'url': requested, 'final_url': final, 'depth': depth, 'bytes': len(data or b'')})

            # ---- STAGE 2: only target-associated HTML nodes ----
            candidates = []
            seen = set()

            def add_candidate(kind, raw, label='', attribute=None, context=''):
                if not raw:
                    return
                key = (kind, raw, label[:120], attribute or '')
                if key in seen:
                    return
                seen.add(key)
                candidates.append(candidate_item(kind, raw, page_base, label, attribute, context))

            # Anchor: inspect anchors whose own text/title/aria or nearby card
            # text contains the complete query. Nearby text is limited so the
            # funnel cannot explode into the whole 5MB page.
            for a in soup.find_all('a', href=True):
                label = ' '.join(filter(None, [
                    a.get_text(' ', strip=True), a.get('title'), a.get('aria-label'), a.get('data-product-name')
                ]))
                parent_text = ''
                parent = a.parent
                if parent is not None:
                    parent_text = parent.get_text(' ', strip=True)[:800]
                grand_text = ''
                if parent is not None and parent.parent is not None:
                    grand_text = parent.parent.get_text(' ', strip=True)[:1200]
                context = label or parent_text or grand_text
                if has_tokens(label) or has_tokens(parent_text) or has_tokens(grand_text):
                    add_candidate('query_anchor', a.get('href'), label, context=context)

            # Attributes on the same target-associated nodes.
            navigation_attrs = (
                'value', 'data-value', 'data-filter-url', 'data-option-url',
                'data-redirect-url', 'data-url', 'data-href', 'data-link',
                'data-product-url', 'data-product-link', 'data-target',
                'data-next-url', 'data-next', 'data-load-more-url',
                'data-pagination-url',
            )
            for node in soup.find_all(True):
                own = node.get_text(' ', strip=True)[:1000]
                if not has_tokens(own):
                    continue
                context = own[:1200]
                for attr in navigation_attrs:
                    raw = node.get(attr)
                    if raw:
                        add_candidate('query_attribute', raw, own, attr, context)

            # JSON-LD: only objects whose serialized content contains all
            # tokens; then inspect their URL field exactly.
            for obj in _jsonld(soup):
                try:
                    blob = norm(json.dumps(obj, ensure_ascii=False))
                except Exception:
                    blob = norm(str(obj))
                if has_tokens(blob) and obj.get('url'):
                    add_candidate('query_jsonld', obj.get('url'), str(obj.get('name') or obj.get('title') or ''), 'url', blob[:1200])

            # Embedded URLs: same extraction family as production, but filtered
            # immediately by the surrounding raw-text window containing the
            # complete query. This is the decisive narrowing stage.
            try:
                raw_html = html.unescape(data.decode('utf-8', 'ignore'))
                raw_html = raw_html.replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')
                host_patterns = {urllib.parse.urlparse(base).netloc.lower() for base in _discovery_bases(store)}
                url_re = re.compile(r"https?://[^\"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^\"'\s<>\\]+", re.I)
                for m in url_re.finditer(raw_html):
                    lo = max(0, m.start() - 900)
                    hi = min(len(raw_html), m.end() + 900)
                    context = raw_html[lo:hi]
                    if not has_tokens(context):
                        continue
                    absolute = urllib.parse.urljoin(page_base, m.group(0)).split('#', 1)[0]
                    parsed = urllib.parse.urlparse(absolute)
                    if parsed.netloc.lower() not in host_patterns:
                        continue
                    add_candidate('query_embedded', m.group(0), '', None, context)
            except Exception:
                pass

            page_inspections.append({
                'page': query_pages[-1],
                'candidate_count': len(candidates),
                'candidates': candidates[:200],
                'query_product_hits': [x for x in candidates if x['query_product_hit']],
            })

    all_candidates = []
    for inspection in page_inspections:
        all_candidates.extend(inspection['candidates'])
    query_product_hits = [x for x in all_candidates if x['query_product_hit']]
    product_classification_hits = [x for x in all_candidates if x['classification'] == 'PRODUCT']

    if query_product_hits:
        diagnosis = 'QUERY_PRODUCT_URL_RETAINED_BY_CLASSIFIER'
    elif product_classification_hits:
        diagnosis = 'TARGET_ASSOCIATED_URLS_FOUND_BUT_QUERY_NOT_IN_CLASSIFIED_URL'
    elif query_pages:
        diagnosis = 'TARGET_PAGE_REACHED_URL_CLASSIFIER_REJECTS_TARGET_CANDIDATES'
    else:
        diagnosis = 'TARGET_PAGE_NOT_REACHED'

    return {
        'ok': True,
        'diagnostic': diagnostic,
        'store': store,
        'query': query,
        'required_tokens': required_tokens,
        'production_search_called': False,
        'database_written': False,
        'parameters': {'max_pages': max_pages, 'max_depth': max_depth, 'max_events': max_events},
        'stage_1': {
            'visited': len(visited),
            'successes': successes,
            'errors_count': len(errors),
            'errors': errors[:100],
            'query_pages': query_pages,
        },
        'stage_2': {
            'pages_inspected': len(page_inspections),
            'candidate_count': len(all_candidates),
            'query_product_hits': query_product_hits[:100],
            'product_classification_hits': product_classification_hits[:100],
            'rejected_target_candidates': [x for x in all_candidates if x['classification'] != 'PRODUCT'][:200],
            'page_inspections': page_inspections,
        },
        'diagnosis': diagnosis,
        'elapsed_sec': round(time.time() - started, 2),
    }

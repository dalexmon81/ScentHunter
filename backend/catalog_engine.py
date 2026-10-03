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
        # Official localized Deloox storefronts. This is host-level catalog
        # coverage only; no product, brand, or query-specific URL is used.
        'https://www.deloox.be',
        'https://www.deloox.com',
        'https://www.deloox.nl',
        'https://www.deloox.lu',
        'https://www.deloox.es',
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
    r'kategorie|kategorien|categories|collection|collections|brand|brands|'
    r'marca|marque|sitemap|'
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



_SEARCH_FTS_TABLE = 'catalog_search_fts'
_SEARCH_FTS_SCHEMA_VERSION = '1'


def _ensure_search_fts(conn):
    """Create and maintain the persistent local-search FTS5 index."""
    try:
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS catalog_search_fts
               USING fts5(
                   store UNINDEXED,
                   url UNINDEXED,
                   search_text,
                   tokenize='unicode61 remove_diacritics 2'
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS catalog_search_fts_meta(
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL
               )"""
        )
        row = conn.execute(
            "SELECT value FROM catalog_search_fts_meta WHERE key='schema_version'"
        ).fetchone()
        version = str(row['value']) if row else ''
        if version != _SEARCH_FTS_SCHEMA_VERSION:
            conn.execute("DELETE FROM catalog_search_fts")
            conn.execute(
                """INSERT INTO catalog_search_fts(store,url,search_text)
                   SELECT u.store,u.url,
                          trim(COALESCE(u.slug,'') || ' ' ||
                               COALESCE(p.name,'') || ' ' ||
                               COALESCE(p.brand,''))
                     FROM store_urls u
                     LEFT JOIN store_products p
                       ON p.store=u.store AND p.url=u.url
                      AND p.fetch_status='OK'
                    WHERE u.active=1"""
            )
            conn.execute(
                """INSERT INTO catalog_search_fts_meta(key,value)
                   VALUES('schema_version',?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (_SEARCH_FTS_SCHEMA_VERSION,),
            )
            conn.commit()
        _ensure_search_fts_triggers(conn)
        return True
    except sqlite3.OperationalError:
        return False


def _ensure_search_fts_triggers(conn):
    """Keep the FTS candidate index synchronized with catalog mutations."""
    trigger_sql = (
        """
        CREATE TRIGGER IF NOT EXISTS catalog_search_fts_store_urls_ai
        AFTER INSERT ON store_urls
        BEGIN
            DELETE FROM catalog_search_fts WHERE store=NEW.store AND url=NEW.url;
            INSERT INTO catalog_search_fts(store,url,search_text)
            SELECT NEW.store,NEW.url,
                   trim(COALESCE(NEW.slug,'') || ' ' ||
                        COALESCE(p.name,'') || ' ' || COALESCE(p.brand,''))
              FROM (SELECT 1) AS one
              LEFT JOIN store_products p
                ON p.store=NEW.store AND p.url=NEW.url
               AND p.fetch_status='OK'
             WHERE NEW.active=1;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS catalog_search_fts_store_urls_au
        AFTER UPDATE OF store,url,slug,active ON store_urls
        BEGIN
            DELETE FROM catalog_search_fts WHERE store=OLD.store AND url=OLD.url;
            DELETE FROM catalog_search_fts WHERE store=NEW.store AND url=NEW.url;
            INSERT INTO catalog_search_fts(store,url,search_text)
            SELECT NEW.store,NEW.url,
                   trim(COALESCE(NEW.slug,'') || ' ' ||
                        COALESCE(p.name,'') || ' ' || COALESCE(p.brand,''))
              FROM (SELECT 1) AS one
              LEFT JOIN store_products p
                ON p.store=NEW.store AND p.url=NEW.url
               AND p.fetch_status='OK'
             WHERE NEW.active=1;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS catalog_search_fts_store_urls_ad
        AFTER DELETE ON store_urls
        BEGIN
            DELETE FROM catalog_search_fts WHERE store=OLD.store AND url=OLD.url;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS catalog_search_fts_store_products_ai
        AFTER INSERT ON store_products
        BEGIN
            DELETE FROM catalog_search_fts WHERE store=NEW.store AND url=NEW.url;
            INSERT INTO catalog_search_fts(store,url,search_text)
            SELECT u.store,u.url,
                   trim(COALESCE(u.slug,'') || ' ' ||
                        COALESCE(NEW.name,'') || ' ' || COALESCE(NEW.brand,''))
              FROM store_urls u
             WHERE u.store=NEW.store AND u.url=NEW.url
               AND u.active=1;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS catalog_search_fts_store_products_au
        AFTER UPDATE OF store,url,name,brand,fetch_status ON store_products
        BEGIN
            DELETE FROM catalog_search_fts WHERE store=OLD.store AND url=OLD.url;
            INSERT INTO catalog_search_fts(store,url,search_text)
            SELECT u.store,u.url,
                   trim(COALESCE(u.slug,'') || ' ' ||
                        COALESCE(NEW.name,'') || ' ' || COALESCE(NEW.brand,''))
              FROM store_urls u
             WHERE u.store=NEW.store AND u.url=NEW.url
               AND u.active=1;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS catalog_search_fts_store_products_ad
        AFTER DELETE ON store_products
        BEGIN
            DELETE FROM catalog_search_fts WHERE store=OLD.store AND url=OLD.url;
            INSERT INTO catalog_search_fts(store,url,search_text)
            SELECT u.store,u.url,trim(COALESCE(u.slug,''))
              FROM store_urls u
             WHERE u.store=OLD.store AND u.url=OLD.url AND u.active=1;
        END
        """,
    )
    for sql in trigger_sql:
        conn.execute(sql)


def _fts_query_for_tokens(token_set):
    """Build a safe FTS5 AND query from normalized search tokens."""
    parts = []
    for token in token_set:
        token = str(token or '').strip()
        if token:
            parts.append('"' + token.replace('"', '""') + '"')
    return ' AND '.join(parts)


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
        _ensure_search_fts(conn)
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
        # Persistent HTML catalog frontier. This is deliberately separate from
        # hydration_queue: discovery tracks catalog/navigation pages, while
        # hydration tracks product pages. Deloox needs durable frontier state
        # because its sitemap endpoints are unreliable and the HTML catalog is
        # too large to finish in one bounded process.
        conn.execute("""CREATE TABLE IF NOT EXISTS catalog_discovery_queue(
            store TEXT NOT NULL,
            url TEXT NOT NULL,
            depth INTEGER NOT NULL DEFAULT 0,
            priority INTEGER NOT NULL DEFAULT 100,
            source TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at REAL NOT NULL DEFAULT 0,
            leased_until REAL,
            lease_token TEXT,
            first_seen_at REAL NOT NULL,
            last_started_at REAL,
            last_finished_at REAL,
            last_error TEXT,
            PRIMARY KEY(store,url)
        )""")
        # Older deployments may already have catalog_discovery_queue without
        # the persistent priority column. Migrate it in place before the
        # frontier is claimed. The priority is structural only and is derived
        # from the same generic URL-priority function used by the in-memory
        # HTML crawler.
        columns = {
            row['name']
            for row in conn.execute('PRAGMA table_info(catalog_discovery_queue)').fetchall()
        }
        if 'priority' not in columns:
            conn.execute(
                'ALTER TABLE catalog_discovery_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 100'
            )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_catalog_discovery_ready ON catalog_discovery_queue(store,state,available_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_catalog_discovery_priority ON catalog_discovery_queue(store,state,available_at,priority,depth,url)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_catalog_discovery_lease ON catalog_discovery_queue(store,state,leased_until)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_catalog_discovery_finished ON catalog_discovery_queue(store,state,last_finished_at)')

        # Backfill the persistent Deloox frontier after migration. This is
        # intentionally independent of any search query or product identity.
        # Existing rows are reprioritized from their URL structure so the
        # current backlog benefits immediately after deployment.
        priority_rows = conn.execute(
            """SELECT url,depth,source
                 FROM catalog_discovery_queue
                WHERE store='deloox'"""
        ).fetchall()
        if priority_rows:
            conn.executemany(
                """UPDATE catalog_discovery_queue
                      SET priority=?
                    WHERE store='deloox' AND url=?""",
                [
                    (
                        int(_html_discovery_priority(
                            'deloox',
                            row['url'],
                            int(row['depth'] or 0),
                            row['source'] or '',
                        )[0]),
                        row['url'],
                    )
                    for row in priority_rows
                ],
            )
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


def _looks_product(url, store=None):
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
    # ParfumZentrum exposes product pages with a `_z<id>` suffix, while
    # brand/category/navigation pages use a `_v<id>` suffix. Keep the rule
    # retailer-generic: it distinguishes URL grammar, not product identity.
    if store == 'parfumzentrum':
        return bool(re.search(r'(?:^|_)z\d+/?$', p.path, re.I))
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



def _sync_deloox_search_index(product_urls):
    """Update an existing Deloox search index without forcing a full rebuild."""
    if not product_urls:
        return
    with _LOCAL_SEARCH_INDEX_LOCK:
        cached = _LOCAL_SEARCH_INDEX_CACHE.get('deloox')
        if not cached:
            return

        postings = cached['postings']
        url_tokens = cached['url_tokens']

        for url, lastmod in product_urls.items():
            # Discovery gives us the canonical product URL/slug. Hydration will
            # later enrich the same index entry with product name and brand.
            old_tokens = url_tokens.get(url, set())
            for token in old_tokens:
                bucket = postings.get(token)
                if not bucket:
                    continue
                bucket.discard(url)
                if not bucket:
                    postings.pop(token, None)

            new_tokens = set(norm(url_slug(url)).split())
            url_tokens[url] = new_tokens
            for token in new_tokens:
                postings.setdefault(token, set()).add(url)

        active_count = sum(1 for _ in url_tokens)
        cached['signature'] = active_count


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
            # Deloox discovery is intentionally incremental: a bounded run is
            # only one slice of a persistent HTML graph. Never deactivate the
            # previously discovered Deloox catalog merely because this run did
            # not reach those branches. A real product disappearance is handled
            # by product-page hydration/HTTP status, not by crawl omission.
            # Sabina discovery is also incremental. Its HTML legacy catalog
            # surface is bounded by time, so a run can legitimately discover
            # only a subset of the existing catalog. Never deactivate known
            # Sabina URLs merely because this run did not reach them.
            if store not in ('deloox', 'sabina'):
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
    if status == 'DISCOVERY_OK' and store == 'deloox':
        _sync_deloox_search_index(product_urls)
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
        # Deloox's public search is also a retailer-owned catalog surface.
        # These are fixed, broad fragrance terms used only by background
        # catalog discovery; the user's search query is never injected here.
        'https://www.deloox.be/chercher.html?q=parfum',
        'https://www.deloox.be/chercher.html?q=perfume',
        'https://www.deloox.be/chercher.html?q=fragrance',
        'https://www.deloox.com/chercher.html?q=parfum',
        'https://www.deloox.com/chercher.html?q=perfume',
        'https://www.deloox.com/chercher.html?q=fragrance',
        'https://www.deloox.be/en/search?query=parfum',
        'https://www.deloox.be/en/search?query=perfume',
        'https://www.deloox.be/en/search?query=fragrance',
        'https://www.deloox.com/en/search?query=parfum',
        'https://www.deloox.com/en/search?query=perfume',
        'https://www.deloox.com/en/search?query=fragrance',
    ),
    'sabina': (
        'https://www.sabina.com/it/',
        'https://www.sabina.com/it/6-profumi-di-donna',
        'https://www.sabina.com/it/7-profumi-da-uomo',
        'https://www.sabina.com/it/30-profumi-donna',
        'https://www.sabina.com/it/31-profumi-uomo',
        'https://www.sabina.com/it/890-profumeria-di-nicchia',
        'https://www.sabina.com/it/s/48/profumi-donna-profumi-uomo',
        # Sabina's legacy native search is a real catalog enumeration
        # surface. The live storefront exposes its legacy product-ID field
        # through the native `?s=` parameter; the `search_query=` variant used
        # by the old single-letter probes returns no legacy product IDs.
        #
        # These are generic fragrance terms, not product/brand-specific
        # queries. Multiple overlapping terms intentionally provide cumulative
        # catalog coverage without coupling discovery to the user's search.
        'https://www.sabina.com/it/ricerca_old?s=parfum',
        'https://www.sabina.com/it/ricerca_old?s=extrait',
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
        # Canonical Sabina product pages use a numeric product id followed by
        # a slug and end in .html. Sabina's legacy storefront also exposes
        # PrestaShop product-controller URLs containing id_product. Those URLs
        # are generic product resolvers: hydration follows the HTTP redirect
        # to the canonical .html URL. No product id or product name is embedded.
        if re.search(r'/\d+-[^/]+\.html$', low, re.I):
            return absolute
        if low.endswith('/index.php'):
            params = urllib.parse.parse_qs(p.query, keep_blank_values=False)
            controllers = {str(x).strip().lower() for x in params.get('controller', [])}
            ids = [str(x).strip() for x in params.get('id_product', []) if str(x).strip().isdigit()]
            if 'product' in controllers and ids:
                return absolute
        return None
    return absolute if _looks_product(absolute, store) else None


def _sabina_legacy_product_urls(data, page_base):
    """Extract generic Sabina product IDs exposed by legacy catalog HTML.

    Sabina's legacy search can expose product IDs through its controller state
    even when the corresponding product card/link is not present in the HTML.
    Those IDs are valid product identifiers, but they are not themselves
    canonical URLs. Convert them to the standard PrestaShop product-controller
    resolver URL so the normal hydration path can follow the retailer's own
    redirect to the canonical product URL.

    This function is deliberately independent of query text, product names,
    brands and individual product IDs.
    """
    if not data:
        return set()
    try:
        raw = data.decode('utf-8', 'ignore') if isinstance(data, (bytes, bytearray)) else str(data)
    except Exception:
        return set()

    raw = html.unescape(raw)
    raw = raw.replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')

    ids = set()

    # Sabina exposes the legacy result IDs as the value of a hidden input
    # whose id/name identifies the controller field. Parse attributes rather
    # than relying on a particular attribute order in the HTML.
    try:
        soup = BeautifulSoup(raw, 'html.parser')
        for node in soup.find_all(
            attrs={'id': re.compile(r'^af_controller_product_ids$', re.I)}
        ):
            value = node.get('value') or node.get_text(' ', strip=True)
            for product_id in re.findall(r'(?<!\d)\d+(?!\d)', value or ''):
                ids.add(product_id)
        for node in soup.find_all(
            attrs={'name': re.compile(r'^af_controller_product_ids$', re.I)}
        ):
            value = node.get('value') or node.get_text(' ', strip=True)
            for product_id in re.findall(r'(?<!\d)\d+(?!\d)', value or ''):
                ids.add(product_id)
    except Exception:
        pass

    # Also accept the same controller field when embedded in JavaScript/JSON
    # rather than an HTML input element.
    for match in re.finditer(
        r'af_controller_product_ids\\s*[^=]{0,80}=\\s*[\"\']([^\"\']*)[\"\']',
        raw,
        re.I,
    ):
        for value in re.findall(r'(?<!\d)\d+(?!\d)', match.group(1)):
            ids.add(value)

    for pattern in (
        r"(?:data-id-product|data-product-id|data-id_product)\\s*=\\s*[\"\'](\\d+)[\"\']",
        r"[\"\'](?:id_product|product_id)[\"\']\\s*[:=]\\s*[\"\']?(\\d+)",
    ):
        for match in re.finditer(pattern, raw, re.I):
            ids.add(match.group(1))

    return {
        urllib.parse.urljoin(
            page_base,
            f'/index.php?controller=product&id_product={product_id}',
        )
        for product_id in sorted(ids, key=lambda value: int(value))[:500]
    }

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
        # Deloox exposes a public search surface which is useful for
        # background catalog enumeration. It is accepted only as a generic
        # retailer navigation page; product-specific/user queries are not
        # introduced by catalog discovery.
        if re.search(r'/(?:chercher|search)(?:\.html)?$', path, re.I):
            if re.search(r'(?:^|&)(?:q|query)=', p.query, re.I):
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

    # Deloox's native public search is a catalog enumeration surface. Keep
    # its generic background seeds ahead of the broad frontier so the search
    # surface is actually exercised during a bounded discovery run. This is
    # URL-structure based only; no user query or product identity is used.
    if (
        store == 'deloox'
        and re.search(r'/(?:chercher|search)(?:\.html)?$', path, re.I)
        and re.search(r'(?:^|&)(?:q|query)=', p.query, re.I)
    ):
        score = 0
    # Sabina's native legacy search is a real catalog/navigation surface.
    # Give the native `?s=` form highest priority so generic catalog probes are
    # executed before the broad category graph consumes the bounded crawl.
    elif (
        store == 'sabina'
        and path.rstrip('/') in ('/it/ricerca_old', '/it/ricerca')
        and re.search(r'(?:^|&)s=', p.query, re.I)
    ):
        score = 0
    # Catalog index pages are high-value navigation surfaces because they
    # expose the next level of category/brand pages. This is structural only:
    # no specific retailer brand, product name, product id, or user query is used.
    elif re.search(r'/(?:brands?|marques?|marcas|marken)(?:\.html)?$', path, re.I):
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
        score = 1
    elif store == 'sabina' and re.search(r'/ricerca_old(?:/|$)', path, re.I):
        # Sabina's legacy search is a catalog surface and exposes controller
        # product IDs that may not be present in category navigation. Keep it
        # ahead of generic site links without embedding any query/product rule.
        score = 2
    elif re.search(r'(?:page|pagina|offset|start|p=)', p.query, re.I):
        score = 4
    elif path in ('/', '') or path.rstrip('/') in ('/en', '/it', '/de', '/fr', '/nl', '/es'):
        score = 8
    else:
        score = 6

    # Deeper pages are still valid, but breadth-first behavior should only
    # break ties between otherwise equivalent catalog surfaces.
    return (score, depth)

def _deloox_queue_allowed(url):
    """Return True only for URLs on an official configured Deloox host."""
    if not url:
        return False
    try:
        p = urllib.parse.urlparse(url.split('#', 1)[0])
    except Exception:
        return False
    if p.scheme not in ('http', 'https'):
        return False
    allowed_hosts = {
        urllib.parse.urlparse(x).netloc.lower()
        for x in _discovery_bases('deloox')
    }
    return p.netloc.lower() in allowed_hosts


def _deloox_queue_seed():
    """Seed the durable Deloox catalog graph without product-specific URLs."""
    seeds = list(dict.fromkeys(HTML_DISCOVERY_SEEDS.get('deloox', ())))
    for base in _discovery_bases('deloox'):
        base = base.rstrip('/')
        seeds.extend((base + '/', base + '/en/'))
    seeds = list(dict.fromkeys(seeds))
    _deloox_queue_enqueue(
        [(url, 0, 'configured_seed') for url in seeds]
    )
    return seeds


def _deloox_queue_enqueue(items):
    """Durably enqueue catalog/navigation URLs.

    Existing DONE rows are not reset by rediscovery. This is what makes the
    frontier cumulative instead of repeatedly starting from the same branch.
    """
    if not items:
        return 0
    now = time.time()
    conn = db()
    inserted = 0
    try:
        with conn:
            for raw_url, depth, source in items:
                if not raw_url:
                    continue
                url = str(raw_url).split('#', 1)[0]
                if not _deloox_queue_allowed(url):
                    continue
                if depth > HTML_MAX_DEPTH:
                    continue
                listing = _html_listing_url('deloox', url, url, source)
                if not listing:
                    continue
                url = listing
                before = conn.execute(
                    'SELECT 1 FROM catalog_discovery_queue WHERE store=? AND url=?',
                    ('deloox', url),
                ).fetchone()
                conn.execute(
                    """INSERT INTO catalog_discovery_queue(
                           store,url,depth,priority,source,state,attempts,available_at,
                           first_seen_at)
                       VALUES(?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                           depth=MIN(catalog_discovery_queue.depth,excluded.depth),
                           priority=MIN(catalog_discovery_queue.priority,excluded.priority),
                           source=CASE
                               WHEN catalog_discovery_queue.source='' THEN excluded.source
                               ELSE catalog_discovery_queue.source
                           END""",
                    (
                        'deloox',
                        url,
                        int(depth),
                        int(_html_discovery_priority(
                            'deloox', url, int(depth), str(source or '')
                        )[0]),
                        str(source or ''),
                        'PENDING',
                        0,
                        now,
                        now,
                    ),
                )
                if before is None:
                    inserted += 1
    finally:
        conn.close()
    return inserted


def _deloox_queue_recover_stale():
    """Return expired discovery leases to PENDING."""
    now = time.time()
    conn = db()
    try:
        with conn:
            cur = conn.execute(
                """UPDATE catalog_discovery_queue
                   SET state='PENDING',
                       leased_until=NULL,
                       lease_token=NULL,
                       available_at=?
                 WHERE store='deloox'
                   AND state='PROCESSING'
                   AND leased_until IS NOT NULL
                   AND leased_until < ?""",
                (now, now),
            )
            return int(cur.rowcount or 0)
    finally:
        conn.close()


def _deloox_queue_requeue_stale_done(revisit_seconds=86400.0, limit=100):
    """Periodically revisit completed graph nodes so new catalog branches appear."""
    cutoff = time.time() - max(3600.0, float(revisit_seconds))
    conn = db()
    try:
        with conn:
            rows = conn.execute(
                """SELECT url
                     FROM catalog_discovery_queue
                    WHERE store='deloox'
                      AND state='DONE'
                      AND last_finished_at IS NOT NULL
                      AND last_finished_at < ?
                    ORDER BY last_finished_at ASC
                    LIMIT ?""",
                (cutoff, max(1, int(limit))),
            ).fetchall()
            if not rows:
                return 0
            now = time.time()
            conn.executemany(
                """UPDATE catalog_discovery_queue
                      SET state='PENDING',
                          available_at=?,
                          leased_until=NULL,
                          lease_token=NULL,
                          last_error=NULL
                    WHERE store='deloox' AND url=? AND state='DONE'""",
                [(now, row['url']) for row in rows],
            )
            return len(rows)
    finally:
        conn.close()


def _deloox_queue_claim(limit=12, lease_seconds=180):
    """Atomically claim a bounded batch of discovery pages."""
    limit = max(1, min(int(limit), HTML_WORKERS))
    now = time.time()
    token = uuid.uuid4().hex
    conn = db()
    claimed = []
    try:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute(
            """SELECT url,depth,priority,source
                 FROM catalog_discovery_queue
                WHERE store='deloox'
                  AND state IN ('PENDING','ERROR')
                  AND available_at <= ?
                ORDER BY priority ASC, depth ASC, url ASC
                LIMIT ?""",
            (now, limit),
        ).fetchall()
        if not rows:
            conn.commit()
            return []
        leased_until = now + max(30.0, float(lease_seconds))
        for row in rows:
            cur = conn.execute(
                """UPDATE catalog_discovery_queue
                      SET state='PROCESSING',
                          attempts=attempts+1,
                          leased_until=?,
                          lease_token=?,
                          last_started_at=?,
                          last_error=NULL
                    WHERE store='deloox'
                      AND url=?
                      AND state IN ('PENDING','ERROR')
                      AND available_at <= ?""",
                (leased_until, token, now, row['url'], now),
            )
            if cur.rowcount:
                claimed.append(
                    (row['url'], int(row['depth']), row['source'] or '', token)
                )
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _deloox_queue_finish(url, token, ok, error=''):
    """Finish one leased page with bounded retry/backoff."""
    now = time.time()
    conn = db()
    try:
        with conn:
            row = conn.execute(
                """SELECT attempts
                     FROM catalog_discovery_queue
                    WHERE store='deloox' AND url=? AND lease_token=?""",
                (url, token),
            ).fetchone()
            if not row:
                return
            attempts = int(row['attempts'] or 0)
            if ok:
                state = 'DONE'
                available_at = 0
                last_error = None
            else:
                state = 'DEAD' if attempts >= 8 else 'ERROR'
                backoff = (60, 300, 1800, 7200, 21600, 86400)
                available_at = now + backoff[min(max(attempts - 1, 0), len(backoff) - 1)]
                last_error = str(error or 'discovery_error')[:1000]
            conn.execute(
                """UPDATE catalog_discovery_queue
                      SET state=?,
                          available_at=?,
                          leased_until=NULL,
                          lease_token=NULL,
                          last_finished_at=?,
                          last_error=?
                    WHERE store='deloox' AND url=? AND lease_token=?""",
                (state, available_at, now, last_error, url, token),
            )
    finally:
        conn.close()


def _deloox_persist_products(product_urls):
    """Persist discovered Deloox product URLs incrementally.

    This reuses the existing catalog -> hydration handoff. It does not alter
    hydration claiming, workers, retries, or performance-sensitive code.
    """
    if not product_urls:
        return 0
    now = time.time()
    conn = db()
    count = 0
    try:
        with conn:
            for url, lastmod in product_urls.items():
                conn.execute(
                    """INSERT INTO store_urls(
                           store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                           slug=excluded.slug,
                           lastmod=excluded.lastmod,
                           discovered_at=excluded.discovered_at,
                           active=1""",
                    ('deloox', url, url_slug(url), lastmod or '', now),
                )
                conn.execute(
                    """INSERT INTO hydration_queue(
                           store,url,state,attempts,available_at,first_seen_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                           state=CASE
                               WHEN hydration_queue.state='DONE' THEN 'DONE'
                               WHEN hydration_queue.state='PROCESSING'
                                    AND hydration_queue.leased_until > ? THEN 'PROCESSING'
                               ELSE hydration_queue.state
                           END""",
                    ('deloox', url, 'PENDING', 0, now, now, now),
                )
                count += 1
    finally:
        conn.close()
    return count


def _discover_deloox_catalog(seeds, deadline=None):
    """Advance Deloox's persistent catalog graph.

    Deloox's sitemap endpoints are unreliable, so catalog discovery is an
    incremental durable graph crawl. Each run claims a bounded set of
    navigation pages, persists newly discovered frontier nodes, and leaves
    the remaining frontier for the next run. No product name, brand, query,
    or individual product URL is used as a special case.
    """
    if seeds:
        _deloox_queue_enqueue(
            [(url, 0, 'configured_seed') for url in seeds]
        )
    seeded = _deloox_queue_seed()
    recovered = _deloox_queue_recover_stale()
    requeued = _deloox_queue_requeue_stale_done()

    started = time.time()
    product_urls = {}
    errors = []
    visited = 0
    successes = 0

    def process_page(requested, depth, source, result):
        nonlocal visited, successes
        _requested, final, data, error = result
        visited += 1
        if error:
            errors.append(f'{requested} -> {error}')
            return False

        successes += 1
        soup = BeautifulSoup(data, 'html.parser')
        base = final or requested
        listings = []

        def admit(raw, label=''):
            product = _html_product_url('deloox', raw, base)
            if product:
                product_urls[product] = ''
                return
            listing = _html_listing_url('deloox', raw, base, label)
            if listing:
                listings.append((listing, depth + 1, requested))

        for a in soup.find_all('a', href=True):
            admit(a.get('href'), a.get_text(' ', strip=True))

        for node in soup.find_all(True):
            label = node.get_text(' ', strip=True)[:300]
            for attr in (
                'value', 'data-value', 'data-filter-url', 'data-option-url',
                'data-redirect-url', 'data-url', 'data-href', 'data-link',
                'data-next-url', 'data-next', 'data-load-more-url',
                'data-pagination-url',
            ):
                raw = node.get(attr)
                if raw:
                    admit(raw, label)

        for node in soup.find_all(['link'], href=True):
            rel = ' '.join(node.get('rel') or []).lower()
            href = node.get('href')
            if 'next' in rel or re.search(
                r'(?:page|pagina|offset|start|p)=',
                urllib.parse.urlparse(href or '').query,
                re.I,
            ):
                admit(href, 'pagination')

        try:
            for item in _jsonld(soup):
                admit(item.get('url'), 'jsonld_product')
        except Exception:
            pass

        try:
            raw_html = html.unescape(data.decode('utf-8', 'ignore'))
            raw_html = raw_html.replace('\\/', '/')
            raw_html = raw_html.replace('\\u002F', '/').replace('\\u002f', '/')
            for match in re.finditer(
                        r'''https?://[^"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^"'\s<>\\]+''',
                raw_html,
                re.I,
            ):
                admit(
                    urllib.parse.urljoin(base, match.group(0)).split('#', 1)[0],
                    'embedded_navigation',
                )
        except Exception:
            pass

        if listings:
            _deloox_queue_enqueue(listings)
        if product_urls:
            _deloox_persist_products(product_urls)
        return True

    max_run_seconds = 120.0
    if deadline is not None:
        max_run_seconds = max(1.0, float(deadline) - time.time())
    run_deadline = time.time() + min(max_run_seconds, 120.0)

    while time.time() < run_deadline:
        batch = _deloox_queue_claim(limit=HTML_WORKERS, lease_seconds=180)
        if not batch:
            break

        with ThreadPoolExecutor(max_workers=min(HTML_WORKERS, len(batch))) as pool:
            futures = {
                pool.submit(_fetch_html_page, 'deloox', url): (
                    url, depth, source, token
                )
                for url, depth, source, token in batch
            }
            for future in as_completed(futures):
                url, depth, source, token = futures[future]
                try:
                    result = future.result()
                    ok = process_page(url, depth, source, result)
                    if ok:
                        _deloox_queue_finish(url, token, True)
                    else:
                        error = result[3] if len(result) > 3 else 'fetch_error'
                        _deloox_queue_finish(url, token, False, error)
                except Exception as exc:
                    error = f'{type(exc).__name__}:{exc}'
                    errors.append(f'{url} -> {error}')
                    _deloox_queue_finish(url, token, False, error)

        # Never monopolize the process after a batch finishes.
        if time.time() >= run_deadline:
            break

    conn = db()
    try:
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN state='PENDING' THEN 1 ELSE 0 END) AS pending,
                 SUM(CASE WHEN state='PROCESSING' THEN 1 ELSE 0 END) AS processing,
                 SUM(CASE WHEN state='DONE' THEN 1 ELSE 0 END) AS done,
                 SUM(CASE WHEN state='ERROR' THEN 1 ELSE 0 END) AS error,
                 SUM(CASE WHEN state='DEAD' THEN 1 ELSE 0 END) AS dead,
                 COUNT(*) AS total
               FROM catalog_discovery_queue
              WHERE store='deloox'"""
        ).fetchone()
    finally:
        conn.close()

    frontier = {
        'total': int(row['total'] or 0),
        'pending': int(row['pending'] or 0),
        'processing': int(row['processing'] or 0),
        'done': int(row['done'] or 0),
        'error': int(row['error'] or 0),
        'dead': int(row['dead'] or 0),
        'seeded': len(seeded),
        'recovered': recovered,
        'requeued_stale_done': requeued,
    }

    return {
        'product_urls': product_urls,
        'visited': visited,
        'successes': successes,
        'errors': errors[:20],
        'frontier': frontier,
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
                page_base=final or requested

                for a in soup.find_all('a',href=True):
                    href=a.get('href'); label=a.get_text(' ',strip=True)
                    product=_html_product_url(store,href,page_base)
                    if product:
                        product_urls[product]=''
                        continue
                    listing=_html_listing_url(store,href,page_base,label)
                    if listing:
                        add(listing,depth+1,requested)

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

                for node in soup.find_all('link',href=True):
                    rel=' '.join(node.get('rel') or []).lower()
                    if 'next' not in rel:
                        continue
                    listing=_html_listing_url(store,node.get('href'),page_base,'next')
                    if listing:
                        add(listing,depth+1,requested)

                try:
                    for item in _jsonld(soup):
                        raw_url=item.get('url')
                        product=_html_product_url(store,raw_url,page_base)
                        if product:
                            product_urls[product]=''
                except Exception:
                    pass

                if store == 'sabina':
                    for product in _sabina_legacy_product_urls(data, page_base):
                        product_urls[product]=''

                try:
                    raw_html = data.decode('utf-8', 'ignore')
                    raw_html = raw_html.replace('\\/', '/')
                    raw_html = raw_html.replace('\\u002F', '/').replace('\\u002f', '/')
                    host_patterns = {
                        urllib.parse.urlparse(base).netloc.lower()
                        for base in _discovery_bases(store)
                    }
                    candidates = set()
                    for match in re.finditer(
                        r'''https?://[^"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^"'\s<>\\]+''',
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

def diagnose_html_discovery_trace(store, query='', max_pages=120, max_depth=8, max_events=500):
    """READ-ONLY trace of the generic HTML discovery graph."""
    store = str(store or '').strip().lower()
    if store not in HTML_DISCOVERY_SEEDS:
        return {'ok': False, 'diagnostic': 'html-discovery-trace-read-only-v1',
                'error': f'html_discovery_not_configured:{store}', 'store': store}

    try:
        max_pages = max(1, min(int(max_pages or 120), HTML_MAX_PAGES))
    except Exception:
        max_pages = 120
    try:
        max_depth = max(0, min(int(max_depth if max_depth is not None else HTML_MAX_DEPTH), HTML_MAX_DEPTH))
    except Exception:
        max_depth = HTML_MAX_DEPTH
    try:
        max_events = max(50, min(int(max_events or 500), 2000))
    except Exception:
        max_events = 500

    required_tokens = tokens(query)
    queue, queued, visited = [], set(), set()
    events, errors = [], []
    product_urls, listing_urls = set(), set()
    sequence = 0
    query_url_hits, query_page_hits = [], []

    def has_tokens(value):
        value = norm(value)
        return bool(required_tokens) and all(t in value for t in required_tokens)

    def add(url, depth, source=''):
        nonlocal sequence
        if not url:
            return False
        key = url.split('#', 1)[0]
        if key in queued or key in visited or depth > max_depth:
            return False
        if len(queued) >= max_pages * 2:
            return False
        sequence += 1
        priority = _html_discovery_priority(store, key, depth, source)
        heapq.heappush(queue, (priority, sequence, key, depth, source))
        queued.add(key)
        if has_tokens(key) and len(query_url_hits) < 100:
            query_url_hits.append({'url': key, 'depth': depth, 'source': source})
        return True

    seeds = list(dict.fromkeys(HTML_DISCOVERY_SEEDS.get(store, ())))
    for seed in seeds:
        add(seed, 0, 'configured_seed')

    started = time.time()
    successes = 0

    while queue and len(visited) < max_pages and (time.time() - started) < DISCOVERY_HARD_TIMEOUT:
        _priority, _sequence, requested, depth, source = heapq.heappop(queue)
        if requested in visited:
            continue
        visited.add(requested)
        try:
            _requested, final, data, error = _fetch_html_page(store, requested)
        except Exception as exc:
            final, data, error = requested, None, f'{type(exc).__name__}:{exc}'

        event = {'url': requested, 'final_url': final, 'depth': depth,
                 'source': source, 'status': 'ERROR' if error else 'OK'}

        if error:
            event['error'] = error
            errors.append(f'{requested} -> {error}')
            if len(events) < max_events:
                events.append(event)
            continue

        successes += 1
        soup = BeautifulSoup(data, 'html.parser')
        page_text = soup.get_text(' ', strip=True)
        page_hit = has_tokens(page_text)
        if page_hit and len(query_page_hits) < 100:
            query_page_hits.append({'url': requested, 'final_url': final,
                                    'depth': depth, 'bytes': len(data or b'')})

        relevant, product_count, listing_count = [], 0, 0

        def report(kind, url, label='', queued_now=None, attribute=None):
            if not (has_tokens(url) or has_tokens(label)):
                return
            item = {'kind': kind, 'url': url, 'label': label[:200], 'token_hit': True}
            if queued_now is not None:
                item['queued'] = bool(queued_now)
            if attribute:
                item['attribute'] = attribute
            relevant.append(item)

        for a in soup.find_all('a', href=True):
            href, label = a.get('href'), a.get_text(' ', strip=True)
            product = _html_product_url(store, href, final or requested)
            if product:
                product_urls.add(product)
                product_count += 1
                report('product', product, label)
                continue
            listing = _html_listing_url(store, href, final or requested, label)
            if listing:
                listing_urls.add(listing)
                queued_now = add(listing, depth + 1, requested)
                listing_count += 1
                report('listing', listing, label, queued_now)

        navigation_attrs = (
            'data-url','data-href','data-link','data-product-url',
            'data-product-link','data-target','data-next-url','data-next',
            'data-load-more-url','data-pagination-url'
        )
        for node in soup.find_all(True):
            label = node.get_text(' ', strip=True)[:300]
            for attr in navigation_attrs:
                raw = node.get(attr)
                if not raw:
                    continue
                product = _html_product_url(store, raw, final or requested)
                if product:
                    product_urls.add(product)
                    product_count += 1
                    report('product_attribute', product, label, attribute=attr)
                    continue
                listing = _html_listing_url(store, raw, final or requested, label)
                if listing:
                    listing_urls.add(listing)
                    queued_now = add(listing, depth + 1, requested)
                    listing_count += 1
                    report('listing_attribute', listing, label, queued_now, attr)

        for node in soup.find_all('link', href=True):
            rel = ' '.join(node.get('rel') or []).lower()
            if 'next' not in rel:
                continue
            listing = _html_listing_url(store, node.get('href'), final or requested, 'next')
            if listing:
                listing_urls.add(listing)
                queued_now = add(listing, depth + 1, requested)
                listing_count += 1
                report('rel_next', listing, 'next', queued_now)

        try:
            for item in _jsonld(soup):
                product = _html_product_url(store, item.get('url'), final or requested)
                if product:
                    product_urls.add(product)
                    product_count += 1
                    report('jsonld_product', product)
        except Exception:
            pass

        event.update({'bytes': len(data or b''), 'token_page_hit': page_hit,
                      'product_links': product_count, 'listing_links': listing_count,
                      'queue_size_after': len(queue)})
        if relevant:
            event['query_relevant_links'] = relevant[:100]
        if len(events) < max_events:
            events.append(event)

    return {
        'ok': True,
        'diagnostic': 'html-discovery-trace-read-only-v1',
        'store': store,
        'query': query,
        'required_tokens': required_tokens,
        'production_search_called': False,
        'database_written': False,
        'parameters': {'max_pages': max_pages, 'max_depth': max_depth, 'max_events': max_events},
        'seeds': seeds,
        'visited': len(visited),
        'successes': successes,
        'errors_count': len(errors),
        'errors': errors[:50],
        'queue_remaining': len(queue),
        'product_urls_found': len(product_urls),
        'listing_urls_seen': len(listing_urls),
        'query_url_hits': query_url_hits,
        'query_page_hits': query_page_hits,
        'query_relevant_events': [
            e for e in events if e.get('token_page_hit') or e.get('query_relevant_links')
        ][:100],
        'events': events,
        'elapsed_sec': round(time.time() - started, 3),
        'diagnosis': (
            'TRACE_COMPLETE: se la categoria/brand page compare come link ma non viene '
            'accodata, controllare _html_listing_url; se non compare, il problema è '
            'nella superficie di navigazione raggiunta dai seed.'
        ),
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
    # Some retailers publish navigation/landing URLs in their sitemap instead
    # of real product URLs. Keep those URLs as generic HTML-discovery seeds
    # rather than discarding them after the sitemap pass.
    html_sitemap_seeds=set()
    sitemap_successes=0; sitemap_url_entries=0

    sitemap_deadline = min(
        started_at + DISCOVERY_HARD_TIMEOUT,
        started_at + SITEMAP_DISCOVERY_BUDGET,
    )
    while queue and len(visited)<MAX_SITEMAPS_PER_STORE and len(product_urls)<MAX_TOTAL_DISCOVERED_URLS and time.time()<sitemap_deadline:
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
                    elif _looks_product(absolute, store):
                        product_urls[absolute]=lastmod or ''
                        if len(product_urls)>=MAX_TOTAL_DISCOVERED_URLS:
                            break
                    elif store in HTML_DISCOVERY_SEEDS:
                        listing=_html_listing_url(store,absolute,final or sm,'sitemap')
                        if listing:
                            html_sitemap_seeds.add(listing)

    fallback=None
    # Deloox has unreliable sitemap endpoints. Its HTML catalog is therefore
    # advanced through a persistent discovery frontier. Do not run a second
    # in-memory HTML fallback for Deloox: that would restart from the same
    # roots and recreate the starvation problem.
    deloox_graph = None
    if store == 'deloox' and store in HTML_DISCOVERY_SEEDS:
        deloox_graph_budget = min(120, DISCOVERY_HARD_TIMEOUT // 2)
        deloox_graph = _discover_deloox_catalog(
            list(dict.fromkeys(HTML_DISCOVERY_SEEDS[store])),
            started_at + deloox_graph_budget,
        )
        product_urls.update(deloox_graph['product_urls'])

    # Sabina's sitemap is only one catalog surface. Its legacy storefront
    # exposes additional product IDs through HTML controller state
    # (af_controller_product_ids), so Sabina must supplement the sitemap with
    # the generic HTML catalog discovery even when the sitemap already
    # contains many product URLs. This is store-level discovery policy only:
    # no product, brand, name or query is embedded here.
    #
    # Other non-Deloox retailers retain the bounded fallback behaviour.
    if (
        store in HTML_DISCOVERY_SEEDS
        and store != 'deloox'
        and (
            store == 'sabina'
            or len(product_urls) < HTML_FALLBACK_SITEMAP_PRODUCT_THRESHOLD
            or (bool(sitemap_errors) and sitemap_successes == 0)
        )
    ):
        html_seeds=list(dict.fromkeys(
            list(HTML_DISCOVERY_SEEDS[store]) + sorted(html_sitemap_seeds)
        ))
        fallback=_discover_html_catalog(
            store,
            html_seeds,
            started_at + DISCOVERY_HARD_TIMEOUT,
        )
        product_urls.update(fallback['product_urls'])

    diagnostics={
        'visited':len(visited),
        'successes':sitemap_successes,
        'entries':sitemap_url_entries,
        'errors':len(sitemap_errors),
        'timed_out': (time.time()-started_at) >= DISCOVERY_HARD_TIMEOUT,
        'sitemap_budget_exhausted': bool(queue) and time.time() >= sitemap_deadline,
        'sitemap_budget_seconds': SITEMAP_DISCOVERY_BUDGET,
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
    if deloox_graph is not None:
        details.append(
            f'deloox_category_graph=visited:{deloox_graph["visited"]};'
            f'successes:{deloox_graph["successes"]};products:{len(deloox_graph["product_urls"])}'
        )
        if deloox_graph['errors']:
            details.append('deloox_graph_errors=' + ' | '.join(deloox_graph['errors'][:4]))
        frontier = deloox_graph.get('frontier') or {}
        if frontier:
            details.append(
                'deloox_frontier='
                f'total:{frontier.get("total",0)};'
                f'pending:{frontier.get("pending",0)};'
                f'done:{frontier.get("done",0)};'
                f'error:{frontier.get("error",0)};'
                f'dead:{frontier.get("dead",0)}'
            )
    if fallback is not None:
        details.append(
            f'html_fallback=visited:{fallback["visited"]};'
            f'successes:{fallback["successes"]};'
            f'products:{len(fallback["product_urls"])};'
            f'seeds:{len(list(dict.fromkeys(list(HTML_DISCOVERY_SEEDS.get(store, ())) + sorted(html_sitemap_seeds))))}'
        )
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
    """Use an existing store parser only as a product-page parser fallback.

    Parser exceptions are deliberately propagated. The hydration layer must
    preserve the real exception instead of collapsing it into the old opaque
    ``ERROR:RuntimeError`` record.
    """
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


def refresh_url(store, url):
    try:
        status, final, data = http_get(url, timeout=REFRESH_TIMEOUT)
        if status >= 400:
            raise RuntimeError(f'HTTP {status}')

        # Keep the first HTTP response as the primary source of truth.
        # The secondary store parser is allowed to fetch again only as a
        # fallback, but a failed fallback must no longer collapse into the
        # opaque generic RuntimeError that previously hid the real cause.
        item = parse_product(store, final, data)
        primary_ok = bool(item and item.get('name'))
        secondary_ok = False
        if not primary_ok:
            item = _secondary_store_parser(store, final, url)
            secondary_ok = bool(item and item.get('name'))

        if not item or not item.get('name'):
            h1_text = ''
            jsonld_count = 0
            try:
                soup = BeautifulSoup(data or b'', 'html.parser')
                h1 = soup.find('h1')
                h1_text = h1.get_text(' ', strip=True)[:180] if h1 else ''
                jsonld_count = len(_jsonld(soup))
            except Exception:
                pass
            detail = (
                'product_parser_not_found'
                f';http_status={status}'
                f';bytes={len(data or b'')}'
                f';final={final}'
                f';primary_parser={"ok" if primary_ok else "none"}'
                f';secondary_parser={"ok" if secondary_ok else "none"}'
                f';jsonld_products={jsonld_count}'
                f';h1={h1_text!r}'
            )
            print(f'CATALOG PRODUCT PARSER DIAG: store={store} url={url} {detail}', flush=True)
            raise RuntimeError(detail)

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

        # Keep an already-built search index current without invalidating and
        # rebuilding the whole store catalog. The persistent DB remains the
        # source of truth; this only mirrors the hydrated URL in memory.
        _update_local_search_index_product(
            store,
            url,
            slug=url_slug(url),
            name=item.get('name'),
            brand=item.get('brand'),
        )
        return item
    except Exception as exc:
        conn = db()
        conn.execute(
            '''INSERT INTO store_products(store,url,fetched_at,fetch_status)
               VALUES(?,?,?,?)
               ON CONFLICT(store,url) DO UPDATE SET
               fetched_at=excluded.fetched_at,fetch_status=excluded.fetch_status''',
            (
                store,
                url,
                time.time(),
                'ERROR:' + type(exc).__name__ + (f': {exc}' if str(exc) else ''),
            ),
        )
        conn.commit()
        conn.close()

        # A failed refresh is excluded by search_local() because only
        # fetch_status='OK' rows are indexed. Mirror that state in an existing
        # in-memory index so a stale successful product cannot remain searchable.
        _remove_local_search_index_url(store, url)
        return None


def _search_db():
    """Open the catalog database strictly read-only for user-facing search.

    Search must never wait for a discovery/hydration writer to acquire a
    SQLite write lock. The catalog database is already initialized by the
    application; a read-only WAL connection is sufficient for search.
    """
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=2000')
    conn.execute('PRAGMA query_only=ON')
    return conn



def search_local(query, per_store=32, search_terms=None):
    # FTS5 is candidate generation only. Whole-token verification and
    # ProductMatcher remain authoritative for identity.
    raw_terms = search_terms if isinstance(search_terms, (list, tuple)) else [query]
    terms = []
    for value in raw_terms:
        value = str(value or '').strip()
        if value and value not in terms:
            terms.append(value)
    if not terms:
        return []

    token_sets = []
    for term in terms[:80]:
        ts = tuple(tokens(term))
        if ts:
            token_sets.append(ts)
    if not token_sets:
        return []

    conn = _search_db()
    rows = []
    unlimited = per_store is None or int(per_store) <= 0
    limit = None if unlimited else max(1, int(per_store))

    try:
        try:
            fts_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_search_fts'"
            ).fetchone()
        except sqlite3.OperationalError:
            fts_exists = None

        if not fts_exists:
            return _search_local_legacy_sql(conn, token_sets, limit, rows)

        for store in STORES:
            selected_by_url = {}

            for ts in token_sets:
                if limit is not None and len(selected_by_url) >= limit:
                    break

                fts_query = _fts_query_for_tokens(ts)
                if not fts_query:
                    continue

                sql = '''
                    SELECT u.url,u.slug,u.lastmod,
                           p.store AS product_store,
                           p.url AS product_url,
                           p.name AS product_name,
                           p.brand AS product_brand,
                           p.image AS product_image,
                           p.sku AS product_sku,
                           p.gtin AS product_gtin,
                           p.mpn AS product_mpn,
                           p.size_ml AS product_size_ml,
                           p.concentration AS product_concentration,
                           p.gender AS product_gender,
                           p.price AS product_price,
                           p.currency AS product_currency,
                           p.availability AS product_availability,
                           p.fetched_at AS product_fetched_at,
                           p.fetch_status AS fetch_status
                      FROM catalog_search_fts f
                      JOIN store_urls u
                        ON u.store=f.store AND u.url=f.url
                      LEFT JOIN store_products p
                        ON p.store=u.store AND p.url=u.url
                       AND p.fetch_status='OK'
                     WHERE f.store=?
                       AND catalog_search_fts MATCH ?
                       AND u.active=1
                     LIMIT ?
                '''
                candidates = conn.execute(
                    sql, (store, fts_query, max(128, limit or 128))
                ).fetchall()

                for r in candidates:
                    url = str(r['url'] or '').strip()
                    if not url or url in selected_by_url:
                        continue
                    search_text = ' '.join(
                        str(r[key] or '')
                        for key in ('slug', 'product_name', 'product_brand')
                    )
                    normalized_tokens = set(norm(search_text).split())
                    score = sum(1 for token in ts if token in normalized_tokens)
                    if score != len(ts):
                        continue
                    selected_by_url[url] = (score + 10, dict(r))

            ordered = sorted(
                selected_by_url.values(),
                key=lambda item: (-item[0], str(item[1].get('url') or '')),
            )
            if limit is not None:
                ordered = ordered[:limit]

            for _score, r in ordered:
                url = str(r.get('url') or '').strip()
                if not url:
                    continue
                if r.get('product_name'):
                    rows.append({
                        'url': url,
                        'slug': r.get('slug') or '',
                        'lastmod': r.get('lastmod') or '',
                        'name': r.get('product_name') or '',
                        'brand': r.get('product_brand') or '',
                        'image': r.get('product_image') or '',
                        'sku': r.get('product_sku') or '',
                        'gtin': r.get('product_gtin') or '',
                        'mpn': r.get('product_mpn') or '',
                        'size_ml': r.get('product_size_ml'),
                        'concentration': r.get('product_concentration') or '',
                        'gender': r.get('product_gender') or '',
                        'price': r.get('product_price'),
                        'currency': r.get('product_currency') or '',
                        'availability': r.get('product_availability') or '',
                        'fetched_at': r.get('product_fetched_at'),
                        'fetch_status': r.get('fetch_status') or 'OK',
                        'price_num': r.get('product_price'),
                        'store': STORE_LABELS[store],
                        'store_key': store,
                    })
                else:
                    rows.append({
                        'store': STORE_LABELS[store],
                        'store_key': store,
                        'url': url,
                        'name': r.get('slug') or url_slug(url),
                        '_needs_refresh': True,
                    })
        return rows
    finally:
        conn.close()


def _search_local_legacy_sql(conn, token_sets, limit, rows):
    # Compatibility path for SQLite builds without FTS5.
    for store in STORES:
        selected_by_url = {}
        for ts in token_sets:
            if limit is not None and len(selected_by_url) >= limit:
                break
            clauses = []
            params = []
            for token in ts:
                token = str(token or '').strip()
                if not token:
                    continue
                pattern = f'%{token}%'
                clauses.append('(u.slug LIKE ? OR p.name LIKE ? OR p.brand LIKE ?)')
                params.extend((pattern, pattern, pattern))
            if not clauses:
                continue

            sql = f'''
                SELECT u.url,u.slug,u.lastmod,
                       p.store AS product_store,p.url AS product_url,
                       p.name AS product_name,p.brand AS product_brand,
                       p.image AS product_image,p.sku AS product_sku,
                       p.gtin AS product_gtin,p.mpn AS product_mpn,
                       p.size_ml AS product_size_ml,
                       p.concentration AS product_concentration,
                       p.gender AS product_gender,p.price AS product_price,
                       p.currency AS product_currency,
                       p.availability AS product_availability,
                       p.fetched_at AS product_fetched_at,
                       p.fetch_status AS fetch_status
                  FROM store_urls u
                  LEFT JOIN store_products p
                    ON p.store=u.store AND p.url=u.url
                   AND p.fetch_status='OK'
                 WHERE u.store=? AND u.active=1
                   AND {' AND '.join(clauses)}
                 LIMIT ?
            '''
            candidates = conn.execute(
                sql, [store, *params, max(128, limit or 128)]
            ).fetchall()
            for r in candidates:
                url = str(r['url'] or '').strip()
                if not url or url in selected_by_url:
                    continue
                search_text = ' '.join(
                    str(r[key] or '') for key in ('slug','product_name','product_brand')
                )
                normalized_tokens = set(norm(search_text).split())
                score = sum(1 for token in ts if token in normalized_tokens)
                if score != len(ts):
                    continue
                selected_by_url[url] = (score + 10, dict(r))

        ordered = sorted(
            selected_by_url.values(),
            key=lambda item: (-item[0], str(item[1].get('url') or '')),
        )
        if limit is not None:
            ordered = ordered[:limit]

        for _score, r in ordered:
            url = str(r.get('url') or '').strip()
            if not url:
                continue
            if r.get('product_name'):
                rows.append({
                    'url': url,'slug': r.get('slug') or '',
                    'lastmod': r.get('lastmod') or '',
                    'name': r.get('product_name') or '',
                    'brand': r.get('product_brand') or '',
                    'image': r.get('product_image') or '',
                    'sku': r.get('product_sku') or '',
                    'gtin': r.get('product_gtin') or '',
                    'mpn': r.get('product_mpn') or '',
                    'size_ml': r.get('product_size_ml'),
                    'concentration': r.get('product_concentration') or '',
                    'gender': r.get('product_gender') or '',
                    'price': r.get('product_price'),
                    'currency': r.get('product_currency') or '',
                    'availability': r.get('product_availability') or '',
                    'fetched_at': r.get('product_fetched_at'),
                    'fetch_status': r.get('fetch_status') or 'OK',
                    'price_num': r.get('product_price'),
                    'store': STORE_LABELS[store],'store_key': store,
                })
            else:
                rows.append({
                    'store': STORE_LABELS[store],'store_key': store,
                    'url': url,'name': r.get('slug') or url_slug(url),
                    '_needs_refresh': True,
                })
    return rows


def refresh_candidates(rows, cancel_event=None, deadline=None):
    """Refresh only catalog candidates that do not yet have page data.

    Cancellation is cooperative and the optional deadline is a hard search
    budget. Pending futures are cancelled when either condition is reached;
    running HTTP requests are allowed to finish their bounded REFRESH_TIMEOUT,
    but the executor is never waited on after cancellation/deadline expiry.
    """
    jobs = [(r['store_key'], r['url']) for r in rows if r.get('_needs_refresh')]
    if not jobs:
        return []
    out = []
    pool = ThreadPoolExecutor(max_workers=min(REFRESH_WORKERS, len(jobs)))
    futures = [pool.submit(refresh_url, store, url) for store, url in jobs]
    cancelled = False
    try:
        pending = set(futures)
        while pending:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                for future in pending:
                    future.cancel()
                break
            if deadline is not None and time.monotonic() >= float(deadline):
                cancelled = True
                for future in pending:
                    future.cancel()
                break
            done = [future for future in list(pending) if future.done()]
            if not done:
                time.sleep(0.05)
                continue
            for future in done:
                pending.discard(future)
                try:
                    item = future.result()
                    if item:
                        out.append(item)
                except Exception:
                    pass
        if cancelled:
            return out
        return out
    finally:
        # Never make a cancelled user search wait for all old refresh workers.
        # Running workers are bounded by REFRESH_TIMEOUT; they will close their
        # own DB connections when finished.
        pool.shutdown(wait=not cancelled, cancel_futures=cancelled)


def hydration_pending_counts():
    """Return active discovered URLs that are not successfully hydrated."""
    conn = db()
    out = {}
    try:
        for store in STORES:
            row = conn.execute(
                """SELECT COUNT(*) c
                   FROM store_urls u
                   LEFT JOIN store_products p
                     ON p.store=u.store AND p.url=u.url
                   WHERE u.store=? AND u.active=1
                     AND (p.url IS NULL OR p.fetch_status != 'OK')""",
                (store,),
            ).fetchone()
            out[store] = int(row['c'] if row else 0)
    finally:
        conn.close()
    return out


def _ensure_hydration_queue():
    """Backfill the durable queue from every currently active discovered URL.

    This makes the new queue safe to introduce on an already-populated Fly
    volume: the existing ~65k store_urls rows become durable work items without
    requiring another discovery run.
    """
    now = time.time()
    conn = db()
    try:
        with conn:
            # Older catalog versions could accidentally persist category/listing
            # URLs (for example Shopify /collections/... pages) as product URLs.
            # Remove those invalid catalog entries before rebuilding the durable
            # hydration queue. This is generic and applies to every store.
            invalid_rows = conn.execute(
                "SELECT store,url FROM store_urls WHERE active=1"
            ).fetchall()
            for r in invalid_rows:
                if _looks_product(r['url'], r['store']):
                    continue
                conn.execute(
                    "DELETE FROM hydration_queue WHERE store=? AND url=?",
                    (r['store'], r['url']),
                )
                conn.execute(
                    "UPDATE store_urls SET active=0 WHERE store=? AND url=?",
                    (r['store'], r['url']),
                )

            rows = conn.execute(
                """SELECT u.store,u.url
                   FROM store_urls u
                   WHERE u.active=1
                     AND NOT EXISTS (
                         SELECT 1 FROM hydration_queue q
                         WHERE q.store=u.store AND q.url=u.url
                     )"""
            ).fetchall()
            for r in rows:
                existing = conn.execute(
                    "SELECT 1 FROM store_products WHERE store=? AND url=? AND fetch_status='OK'",
                    (r['store'], r['url']),
                ).fetchone()
                state = 'DONE' if existing else 'PENDING'
                conn.execute(
                    """INSERT OR IGNORE INTO hydration_queue(
                           store,url,state,attempts,available_at,first_seen_at)
                       VALUES(?,?,?,?,?,?)""",
                    (r['store'], r['url'], state, 0, now, now),
                )
        return len(rows)
    finally:
        conn.close()


def recover_stale_tasks():
    """Return abandoned PROCESSING leases to PENDING after a restart/crash."""
    now = time.time()
    conn = db()
    try:
        with conn:
            result = conn.execute(
                """UPDATE hydration_queue
                   SET state='PENDING',
                       leased_until=NULL,
                       lease_token=NULL,
                       available_at=?,
                       last_error=COALESCE(last_error,'worker lease expired')
                   WHERE state='PROCESSING'
                     AND (leased_until IS NULL OR leased_until < ?)""",
                (now, now),
            )
            return int(result.rowcount or 0)
    finally:
        conn.close()


def _hydration_store_order(conn):
    """Return a persistent round-robin store order."""
    row = conn.execute(
        "SELECT last_store_index FROM hydration_scheduler WHERE id=1"
    ).fetchone()
    last_index = int(row['last_store_index'] if row else 0)
    n = len(STORES)
    if not n:
        return [], 0
    start = (last_index + 1) % n
    stores = list(STORES)
    return stores[start:] + stores[:start], start


def _claim_one_hydration_task(lease_seconds=HYDRATION_LEASE_SECONDS):
    """Atomically claim one ready URL, with at most two active tasks per store."""
    now = time.time()
    token = uuid.uuid4().hex
    conn = db()
    try:
        conn.execute('BEGIN IMMEDIATE')

        # A worker crash/restart must never strand a URL forever.
        conn.execute(
            """UPDATE hydration_queue
               SET state='PENDING', leased_until=NULL, lease_token=NULL,
                   available_at=?
               WHERE state='PROCESSING'
                 AND (leased_until IS NULL OR leased_until < ?)""",
            (now, now),
        )

        ordered, start_index = _hydration_store_order(conn)
        chosen = None
        chosen_index = None

        for offset, store in enumerate(ordered):
            row = conn.execute(
                """SELECT q.store,q.url,q.attempts
                   FROM hydration_queue q
                   JOIN store_urls u
                     ON u.store=q.store AND u.url=q.url
                   WHERE q.store=?
                     AND u.active=1
                     AND q.state IN ('PENDING','ERROR')
                     AND q.available_at <= ?
                     AND (
                         SELECT COUNT(*)
                         FROM hydration_queue p
                         WHERE p.store=q.store
                           AND p.state='PROCESSING'
                     ) < 2
                   ORDER BY
                     CASE WHEN q.attempts=0 THEN 0 ELSE 1 END,
                     q.available_at ASC,
                     q.first_seen_at ASC
                   LIMIT 1""",
                (store, now),
            ).fetchone()
            if row:
                chosen = row
                chosen_index = (start_index + offset) % len(STORES)
                break

        if not chosen:
            conn.commit()
            return None

        updated = conn.execute(
            """UPDATE hydration_queue
               SET state='PROCESSING',
                   leased_until=?,
                   lease_token=?,
                   last_started_at=?,
                   attempts=attempts+1
               WHERE store=? AND url=?
                 AND state IN ('PENDING','ERROR')
                 AND available_at <= ?""",
            (
                now + float(lease_seconds),
                token,
                now,
                chosen['store'],
                chosen['url'],
                now,
            ),
        ).rowcount

        if updated != 1:
            conn.rollback()
            return None

        conn.execute(
            "UPDATE hydration_scheduler SET last_store_index=? WHERE id=1",
            (int(chosen_index),),
        )
        conn.commit()
        return {
            'store': chosen['store'],
            'url': chosen['url'],
            'lease_token': token,
            'attempts': int(chosen['attempts'] or 0) + 1,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _queue_mark_done(task):
    """Commit the successful product result and close the lease atomically."""
    now = time.time()
    conn = db()
    try:
        # refresh_url() has already persisted the product. We only transition
        # the durable work item here, guarded by its lease token.
        with conn:
            conn.execute(
                """UPDATE hydration_queue
                   SET state='DONE',
                       leased_until=NULL,
                       lease_token=NULL,
                       last_finished_at=?,
                       last_error=NULL,
                       last_http_status=NULL
                   WHERE store=? AND url=? AND lease_token=?
                     AND state='PROCESSING'""",
                (now, task['store'], task['url'], task['lease_token']),
            )
    finally:
        conn.close()


def _queue_mark_error(task, error, http_status=None):
    """Record a retryable error using bounded exponential backoff."""
    now = time.time()
    conn = db()
    try:
        row = conn.execute(
            """SELECT attempts FROM hydration_queue
               WHERE store=? AND url=? AND lease_token=? AND state='PROCESSING'""",
            (task['store'], task['url'], task['lease_token']),
        ).fetchone()
        if not row:
            return

        attempts = int(row['attempts'] or 0)
        idx = min(max(attempts - 1, 0), len(HYDRATION_BACKOFF_SECONDS) - 1)
        delay = float(HYDRATION_BACKOFF_SECONDS[idx])
        jitter = delay * HYDRATION_RETRY_JITTER * (0.5 + (time.time() % 0.5))
        next_time = now + delay + jitter

        # 404/410 and exhausted retries are terminal. Other failures remain
        # retryable and get progressively longer backoff.
        terminal_http = http_status in (404, 410)
        next_state = (
            'DEAD'
            if terminal_http or attempts >= HYDRATION_MAX_ATTEMPTS
            else 'ERROR'
        )
        conn.execute(
            """UPDATE hydration_queue
               SET state=?,
                   available_at=?,
                   leased_until=NULL,
                   lease_token=NULL,
                   last_finished_at=?,
                   last_error=?,
                   last_http_status=?
               WHERE store=? AND url=? AND lease_token=?
                 AND state='PROCESSING'""",
            (
                next_state,
                next_time,
                now,
                str(error)[:1000],
                http_status,
                task['store'],
                task['url'],
                task['lease_token'],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _hydrate_one_task(task):
    """Execute one claimed page fetch and transition its queue state."""
    try:
        item = refresh_url(task['store'], task['url'])
        if item and item.get('name'):
            _queue_mark_done(task)
            return True
        # refresh_url records the concrete fetch failure in store_products.
        conn = db()
        try:
            row = conn.execute(
                "SELECT fetch_status FROM store_products WHERE store=? AND url=?",
                (task['store'], task['url']),
            ).fetchone()
            detail = str(row['fetch_status']) if row and row['fetch_status'] else 'product_parser_not_found'
        finally:
            conn.close()

        match = re.search(r'(?:HTTP\s+|http_status=)(\d+)', detail)
        http_status = int(match.group(1)) if match else None
        _queue_mark_error(task, detail, http_status=http_status)
        return False
    except Exception as exc:
        _queue_mark_error(task, f'{type(exc).__name__}: {exc}')
        return False


def hydrate_catalog_batch(max_urls=2, workers=HYDRATION_WORKERS, deadline=None, stores=None):
    """Process a small durable queue batch.

    Queue initialization/backfill is deliberately not part of this hot loop.
    The queue is initialized once by catalog_hydration_loop() at startup, while
    discovery writes newly discovered URLs directly into hydration_queue.
    The queue itself owns concurrency/fairness. At most one task per store is
    claimed, while the global worker count stays small enough for the 1 GB /
    shared-CPU Fly machine.
    """
    # Do not call _ensure_hydration_queue() here.
    #
    # That function scans the whole active catalog and backfills missing queue
    # rows. Running it before every small hydration batch causes repeated
    # catalog-wide SQLite work and contends with user searches.
    recover_stale_tasks()

    limit = max(1, int(max_urls))
    worker_count = max(1, min(int(workers), HYDRATION_WORKERS, limit))
    tasks = []

    # Claim serially because each claim uses a short BEGIN IMMEDIATE
    # transaction. Once claimed, HTTP work happens completely outside SQLite.
    for _ in range(limit):
        if deadline is not None and time.monotonic() >= float(deadline):
            break
        task = _claim_one_hydration_task()
        if not task:
            break
        tasks.append(task)

    if not tasks:
        return {'selected': 0, 'fetched': 0, 'errors': 0}

    fetched = 0
    errors = 0
    pool = ThreadPoolExecutor(max_workers=min(worker_count, len(tasks)))
    futures = [pool.submit(_hydrate_one_task, task) for task in tasks]
    try:
        for future in as_completed(futures):
            try:
                if future.result():
                    fetched += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
        return {
            'selected': len(tasks),
            'fetched': fetched,
            'errors': errors,
        }
    finally:
        pool.shutdown(wait=True)


def catalog_discovery_loop(stop_event, interval_seconds=300.0):
    """Continuously advance durable catalog discovery in the background.

    This loop is intentionally independent from hydration. It only advances
    the Deloox navigation frontier; search remains read-only and hydration
    keeps its existing workers/claim/retry behavior unchanged.
    """
    pause = max(30.0, float(interval_seconds))
    print(
        f'CATALOG DISCOVERY START store=deloox interval={pause:g}s',
        flush=True,
    )
    while stop_event is None or not stop_event.is_set():
        started = time.time()
        try:
            result = discover_store('deloox')
            frontier = {}
            if isinstance(result, dict):
                # The frontier is also persisted in sync_state.error for
                # operators, so this remains observable without a new API.
                frontier = (result.get('html_fallback') or {}) if False else {}
            print(
                'CATALOG DISCOVERY BATCH '
                f'store=deloox status={result.get("status","unknown") if isinstance(result,dict) else "unknown"} '
                f'count={result.get("count","?") if isinstance(result,dict) else "?"}',
                flush=True,
            )
        except Exception as exc:
            print(
                f'CATALOG DISCOVERY ERROR store=deloox: {type(exc).__name__}: {exc}',
                flush=True,
            )
        elapsed = time.time() - started
        wait_for = max(1.0, pause - elapsed)
        if stop_event is not None:
            stop_event.wait(wait_for)
        else:
            time.sleep(wait_for)


# ---------------------------------------------------------------------------
# Canonical catalog coverage engine
# ---------------------------------------------------------------------------
# The persistent retailer catalog is intentionally store-first, but store-wide
# crawling alone cannot guarantee that a product exposed by a retailer's
# search surface is ever indexed. Coverage therefore runs from the canonical
# identity catalog and feeds the same store_urls/hydration pipeline used by
# normal discovery.
#
# canonical product -> store scraper search -> candidate URL -> hydration
#
# This layer is deliberately generic: no product, brand, retailer-product URL,
# price, or exception is embedded here.

_COVERAGE_SCHEMA_LOCK = threading.Lock()
_COVERAGE_SCHEMA_READY = False
_COVERAGE_CATALOG_CACHE = None
_COVERAGE_CATALOG_MTIME = None
_COVERAGE_INTERVAL_SECONDS = 60.0
_COVERAGE_BATCH_SIZE = 8
_COVERAGE_WORKERS = 2
_COVERAGE_RETRY_SECONDS = 86400.0
_COVERAGE_ERROR_RETRY_SECONDS = 3600.0

_COVERAGE_STORE_MODULES = {
    'bplatz': 'scrapers.bplatz.scraper',
    'deloox': 'scrapers.deloox.scraper',
    'parfumcity': 'scrapers.parfumcity.scraper',
    'parfumzentrum': 'scrapers.parfumzentrum.scraper',
    'perfumemarket': 'scrapers.perfumemarket.scraper',
    'sabina': 'scrapers.sabina.scraper',
    'orioudh': 'scrapers.orioudh.scraper',
    'easycosmetic': 'scrapers.easycosmetic.scraper',
}


def _coverage_ensure_schema():
    global _COVERAGE_SCHEMA_READY
    if _COVERAGE_SCHEMA_READY:
        return
    with _COVERAGE_SCHEMA_LOCK:
        if _COVERAGE_SCHEMA_READY:
            return
        conn = db()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS catalog_coverage(
                    store TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    found_urls INTEGER NOT NULL DEFAULT 0,
                    last_started_at REAL,
                    last_finished_at REAL,
                    next_run_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    PRIMARY KEY(store, product_id)
                )"""
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_catalog_coverage_ready '
                'ON catalog_coverage(state,next_run_at,store)'
            )
            conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_catalog_coverage_product '
                'ON catalog_coverage(product_id,state)'
            )
            conn.commit()
            _COVERAGE_SCHEMA_READY = True
        finally:
            conn.close()


def _coverage_load_catalog():
    """Load the canonical product list once and refresh only when the file changes."""
    global _COVERAGE_CATALOG_CACHE, _COVERAGE_CATALOG_MTIME
    path = BASE_DIR / 'product_catalog.json'
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return []
    if _COVERAGE_CATALOG_CACHE is not None and _COVERAGE_CATALOG_MTIME == mtime:
        return _COVERAGE_CATALOG_CACHE
    try:
        with path.open('r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception as exc:
        print(f'CATALOG COVERAGE CATALOG LOAD ERROR: {type(exc).__name__}:{exc}', flush=True)
        return _COVERAGE_CATALOG_CACHE or []
    products = payload.get('products') if isinstance(payload, dict) else None
    if not isinstance(products, list):
        products = []
    cleaned = []
    for product in reversed(products):
        if not isinstance(product, dict):
            continue
        product_id = str(product.get('product_id') or '').strip()
        canonical_name = str(product.get('canonical_name') or '').strip()
        if product_id and canonical_name:
            cleaned.append(product)
    _COVERAGE_CATALOG_CACHE = cleaned
    _COVERAGE_CATALOG_MTIME = mtime
    return cleaned


def _coverage_queries(product):
    """Build a small generic query set from canonical identity metadata."""
    canonical = str(product.get('canonical_name') or '').strip()
    brand = str(product.get('brand_name') or '').strip()
    aliases = product.get('aliases') or []
    candidates = [canonical]
    if brand and brand.lower() not in canonical.lower():
        candidates.append(f'{brand} {canonical}')
    if isinstance(aliases, list):
        for alias in aliases:
            alias = str(alias or '').strip()
            if alias:
                candidates.append(alias)
            if len(candidates) >= 4:
                break
    out = []
    seen = set()
    for value in candidates:
        key = norm(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out[:4]


def _coverage_seed_tasks(conn, products):
    """Create the complete store x canonical-product coverage matrix idempotently."""
    if not products:
        return
    expected = len(products) * len(STORES)
    existing = int(conn.execute('SELECT COUNT(*) c FROM catalog_coverage').fetchone()['c'] or 0)
    if existing >= expected:
        return
    now = time.time()
    rows = []
    for product in products:
        product_id = str(product.get('product_id') or '').strip()
        canonical = str(product.get('canonical_name') or '').strip()
        queries = _coverage_queries(product)
        if not product_id or not canonical or not queries:
            continue
        primary = queries[0]
        for store in STORES:
            rows.append((store, product_id, canonical, primary, now))
    conn.executemany(
        """INSERT INTO catalog_coverage(
               store,product_id,canonical_name,query,state,next_run_at)
           VALUES(?,?,?,?, 'PENDING', ?)
           ON CONFLICT(store,product_id) DO NOTHING""",
        rows,
    )
    conn.commit()


def _coverage_token_match(text, target):
    """Whole-token generic identity gate; never uses arbitrary substring matches."""
    hay = norm(text)
    needle = norm(target)
    if not hay or not needle:
        return False
    if f' {needle} ' in f' {hay} ':
        return True
    target_tokens = needle.split()
    hay_tokens = set(hay.split())
    return bool(target_tokens) and all(token in hay_tokens for token in target_tokens)


def _coverage_result_matches(product, row):
    canonical = str(product.get('canonical_name') or '').strip()
    if not canonical or not isinstance(row, dict):
        return False
    text = ' '.join(
        str(row.get(key) or '')
        for key in ('name', 'brand', 'title', 'url', 'product_url', 'link')
    )
    if _coverage_token_match(text, canonical):
        return True

    # Retailers may publish a canonical item under a longer catalog alias.
    # Accept only meaningful aliases here; short identity tokens such as a
    # one-letter product code must never become arbitrary substring matches.
    aliases = product.get('aliases') or []
    if isinstance(aliases, list):
        for alias in aliases:
            alias = str(alias or '').strip()
            normalized = norm(alias)
            if len(normalized) < 4 or len(normalized.split()) < 2:
                continue
            if _coverage_token_match(text, alias):
                return True
    return False


def _coverage_allowed_url(store, raw_url):
    if not raw_url:
        return ''
    try:
        url = urllib.parse.urljoin(STORES.get(store, ''), str(raw_url)).split('#', 1)[0]
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ''
    if parsed.scheme not in ('http', 'https'):
        return ''
    host = parsed.netloc.lower().split(':', 1)[0]
    base_host = urllib.parse.urlparse(STORES.get(store, '')).netloc.lower().split(':', 1)[0]
    allowed = {base_host, base_host[4:] if base_host.startswith('www.') else 'www.' + base_host}
    if store == 'deloox':
        allowed.update({
            'deloox.be', 'www.deloox.be', 'deloox.nl', 'www.deloox.nl',
            'deloox.com', 'www.deloox.com', 'deloox.lu', 'www.deloox.lu',
            'deloox.es', 'www.deloox.es',
        })
    return url if host in allowed else ''


def _coverage_persist_urls(store, rows):
    urls = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get('url') or row.get('product_url') or row.get('link')
        url = _coverage_allowed_url(store, raw)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    if not urls:
        return 0
    now = time.time()
    conn = db()
    try:
        with conn:
            for url in urls:
                conn.execute(
                    """INSERT INTO store_urls(store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                           slug=excluded.slug,discovered_at=excluded.discovered_at,active=1""",
                    (store, url, url_slug(url), '', now),
                )
                conn.execute(
                    """INSERT INTO hydration_queue(
                           store,url,state,attempts,available_at,first_seen_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                           state=CASE
                               WHEN hydration_queue.state='DONE' THEN 'DONE'
                               WHEN hydration_queue.state='PROCESSING'
                                    AND hydration_queue.leased_until > ? THEN 'PROCESSING'
                               ELSE hydration_queue.state
                           END""",
                    (store, url, 'PENDING', 0, now, now, now),
                )
        with _LOCAL_SEARCH_INDEX_LOCK:
            _LOCAL_SEARCH_INDEX_CACHE.pop(store, None)
    finally:
        conn.close()
    return len(urls)


def _coverage_run_task(task):
    store = task['store']
    product = task['product']
    queries = _coverage_queries(product)
    module_name = _COVERAGE_STORE_MODULES.get(store)
    if not module_name:
        return {'state': 'ERROR', 'found': 0, 'error': 'store_module_missing'}
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return {'state': 'ERROR', 'found': 0, 'error': f'{type(exc).__name__}:{exc}'}
    search_stream = getattr(module, 'search_stream', None)
    search_fn = getattr(module, 'search', None)
    if not callable(search_stream) and not callable(search_fn):
        return {'state': 'ERROR', 'found': 0, 'error': 'scraper_search_unavailable'}

    matched_rows = []
    errors = []
    for query in queries:
        try:
            if callable(search_stream):
                report = search_stream(query)
                if isinstance(report, dict):
                    rows = report.get('results') or []
                    status = str(report.get('status') or '')
                    if status in {'error', 'timeout', 'blocked', 'unavailable'}:
                        errors.append(str(report.get('error') or status))
                else:
                    rows = report if isinstance(report, list) else []
            else:
                rows = search_fn(query)
                rows = rows if isinstance(rows, list) else []
        except Exception as exc:
            errors.append(f'{type(exc).__name__}:{exc}')
            continue
        for row in rows:
            if _coverage_result_matches(product, row):
                matched_rows.append(row)
        if matched_rows:
            break

    found = _coverage_persist_urls(store, matched_rows)
    if found:
        return {'state': 'FOUND', 'found': found, 'error': None}
    if errors:
        return {'state': 'RETRY', 'found': 0, 'error': errors[0][:1000]}
    return {'state': 'NOT_FOUND', 'found': 0, 'error': None}


def _coverage_claim_tasks(limit):
    _coverage_ensure_schema()
    products = _coverage_load_catalog()
    if not products:
        return []
    now = time.time()
    conn = db()
    try:
        _coverage_seed_tasks(conn, products)
        rows = conn.execute(
            """SELECT store,product_id,canonical_name,query,attempts
                 FROM catalog_coverage
                WHERE next_run_at <= ?
                  AND state IN ('PENDING','NOT_FOUND','RETRY')
                ORDER BY CASE state WHEN 'PENDING' THEN 0 ELSE 1 END,
                         next_run_at,rowid
                LIMIT ?""",
            (now, max(1, int(limit))),
        ).fetchall()
        product_by_id = {str(p.get('product_id')): p for p in products if p.get('product_id')}
        tasks = []
        for row in rows:
            product = product_by_id.get(str(row['product_id']))
            if not product:
                continue
            attempts = int(row['attempts'] or 0) + 1
            conn.execute(
                """UPDATE catalog_coverage
                      SET state='PROCESSING',attempts=?,last_started_at=?,last_error=NULL
                    WHERE store=? AND product_id=?""",
                (attempts, now, row['store'], row['product_id']),
            )
            tasks.append({'store': row['store'], 'product': product, 'attempts': attempts})
        conn.commit()
        return tasks
    finally:
        conn.close()


def _coverage_finish_task(task, result):
    now = time.time()
    state = str(result.get('state') or 'ERROR')
    next_run = now + (_COVERAGE_RETRY_SECONDS if state in {'FOUND','NOT_FOUND'} else _COVERAGE_ERROR_RETRY_SECONDS)
    conn = db()
    try:
        conn.execute(
            """UPDATE catalog_coverage
                  SET state=?,found_urls=?,last_finished_at=?,next_run_at=?,last_error=?
                WHERE store=? AND product_id=?""",
            (
                state, int(result.get('found') or 0), now, next_run, result.get('error'),
                task['store'], str(task['product'].get('product_id') or ''),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def coverage_batch(max_tasks=_COVERAGE_BATCH_SIZE, workers=_COVERAGE_WORKERS):
    """Advance canonical-product coverage in small bounded batches."""
    tasks = _coverage_claim_tasks(max_tasks)
    if not tasks:
        return {'selected': 0, 'found': 0, 'not_found': 0, 'errors': 0}
    found = not_found = errors = 0
    worker_count = max(1, min(int(workers), len(tasks), _COVERAGE_WORKERS))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {pool.submit(_coverage_run_task, task): task for task in tasks}
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {'state': 'ERROR', 'found': 0, 'error': f'{type(exc).__name__}:{exc}'}
            _coverage_finish_task(task, result)
            state = result.get('state')
            if state == 'FOUND':
                found += int(result.get('found') or 0)
            elif state == 'NOT_FOUND':
                not_found += 1
            else:
                errors += 1
    return {'selected': len(tasks), 'found': found, 'not_found': not_found, 'errors': errors}


def coverage_status():
    """Read-only coverage metrics for operators and diagnostics."""
    _coverage_ensure_schema()
    conn = db()
    try:
        rows = conn.execute(
            """SELECT store,COUNT(*) AS total,
                      SUM(CASE WHEN state='PENDING' THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN state='PROCESSING' THEN 1 ELSE 0 END) AS processing,
                      SUM(CASE WHEN state='FOUND' THEN 1 ELSE 0 END) AS found,
                      SUM(CASE WHEN state='NOT_FOUND' THEN 1 ELSE 0 END) AS not_found,
                      SUM(CASE WHEN state='RETRY' THEN 1 ELSE 0 END) AS retry,
                      SUM(CASE WHEN state='ERROR' THEN 1 ELSE 0 END) AS error
                 FROM catalog_coverage GROUP BY store ORDER BY store"""
        ).fetchall()
        return {
            row['store']: {
                'total': int(row['total'] or 0), 'pending': int(row['pending'] or 0),
                'processing': int(row['processing'] or 0), 'found': int(row['found'] or 0),
                'not_found': int(row['not_found'] or 0), 'retry': int(row['retry'] or 0),
                'error': int(row['error'] or 0),
            }
            for row in rows
        }
    finally:
        conn.close()


def catalog_hydration_loop(stop_event, batch_size=2, workers=HYDRATION_WORKERS, pause_seconds=1.0):
    """Continuously hydrate discovered product pages in the background."""
    _ensure_hydration_queue()
    _coverage_ensure_schema()
    recovered = recover_stale_tasks()
    coverage_next_at = 0.0
    print(
        f'CATALOG HYDRATION START batch={batch_size} workers={workers} recovered={recovered}',
        flush=True,
    )
    print(
        f'CATALOG COVERAGE START interval={_COVERAGE_INTERVAL_SECONDS:g}s '
        f'batch={_COVERAGE_BATCH_SIZE} workers={_COVERAGE_WORKERS}',
        flush=True,
    )
    while stop_event is None or not stop_event.is_set():
        try:
            now_mono = time.monotonic()
            if now_mono >= coverage_next_at:
                coverage_result = coverage_batch()
                print(
                    'CATALOG COVERAGE BATCH '
                    f"selected={coverage_result.get('selected')} "
                    f"found={coverage_result.get('found')} "
                    f"not_found={coverage_result.get('not_found')} "
                    f"errors={coverage_result.get('errors')}",
                    flush=True,
                )
                coverage_next_at = now_mono + _COVERAGE_INTERVAL_SECONDS
            result = hydrate_catalog_batch(
                max_urls=max(1, int(batch_size)),
                workers=min(int(workers), HYDRATION_WORKERS),
                deadline=time.monotonic() + max(30.0, float(REFRESH_TIMEOUT) + 5.0),
            )
            if result.get('selected', 0) == 0:
                if stop_event is not None:
                    stop_event.wait(max(5.0, float(pause_seconds)))
                else:
                    time.sleep(max(5.0, float(pause_seconds)))
                continue
            print(
                'CATALOG HYDRATION BATCH '
                f"selected={result.get('selected')} "
                f"fetched={result.get('fetched')} "
                f"errors={result.get('errors')}",
                flush=True,
            )
            if stop_event is not None:
                stop_event.wait(max(0.1, float(pause_seconds)))
            else:
                time.sleep(max(0.1, float(pause_seconds)))
        except Exception as exc:
            print(
                f'CATALOG HYDRATION ERROR: {type(exc).__name__}: {exc}',
                flush=True,
            )
            if stop_event is not None:
                stop_event.wait(5.0)
            else:
                time.sleep(5.0)


def hydration_status():
    """Detailed durable hydration queue status, restricted to active URLs."""
    conn = db()
    out = {}
    try:
        for store in STORES:
            row = conn.execute(
                """SELECT
                     COUNT(*) AS total,
                     SUM(CASE WHEN q.state='PENDING' THEN 1 ELSE 0 END) AS pending,
                     SUM(CASE WHEN q.state='PROCESSING' THEN 1 ELSE 0 END) AS processing,
                     SUM(CASE WHEN q.state='DONE' THEN 1 ELSE 0 END) AS done,
                     SUM(CASE WHEN q.state='ERROR' THEN 1 ELSE 0 END) AS error,
                     SUM(CASE WHEN q.state='DEAD' THEN 1 ELSE 0 END) AS dead,
                     MAX(q.last_finished_at) AS last_finished_at
                   FROM hydration_queue q
                   JOIN store_urls u
                     ON u.store=q.store AND u.url=q.url
                   WHERE q.store=? AND u.active=1""",
                (store,),
            ).fetchone()
            out[store] = {
                'total': int(row['total'] or 0),
                'pending': int(row['pending'] or 0),
                'processing': int(row['processing'] or 0),
                'done': int(row['done'] or 0),
                'error': int(row['error'] or 0),
                'dead': int(row['dead'] or 0),
                'last_finished_at': row['last_finished_at'],
            }
    finally:
        conn.close()
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
        pending = conn.execute(
            '''SELECT COUNT(*) c
               FROM store_urls u
               LEFT JOIN store_products p
                 ON p.store=u.store AND p.url=u.url
               WHERE u.store=? AND u.active=1
                 AND (p.url IS NULL OR p.fetch_status != "OK")''',
            (store,),
        ).fetchone()['c']
        out[store] = {
            'status': derived_status,
            'indexed_urls': count,
            'fetched_products': fetched,
            'pending_hydration': int(pending),
            'hydration_ratio': round((fetched / count), 4) if count else 0.0,
            'finished_at': r['finished_at'] if r else None,
            'age_sec': (now - r['finished_at']) if r and r['finished_at'] else None,
            'error': r['error'] if r else None,
        }
    conn.close()
    return out


if __name__ == '__main__':
    print(json.dumps(sync_all(), indent=2, ensure_ascii=False))

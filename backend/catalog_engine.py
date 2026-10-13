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
import inspect
import json
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
import os
import signal
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
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
    'easycosmetic': 'https://www.easycosmetic.be',
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
    'easycosmetic': (
        # ScentHunter serves the Belgian market: discover Belgian URLs only.
        'https://www.easycosmetic.be',
    ),
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
    'Accept-Language': 'nl-BE,nl;q=0.9,fr-BE,fr;q=0.8,en;q=0.7',
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
HYDRATION_WORKERS = 2
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
    if host in {
        'easycosmetic.de', 'www.easycosmetic.de',
        'easycosmetic.be', 'www.easycosmetic.be',
    }:
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

# Keep background hydration from starting immediately after a foreground search.
# A completed search can be followed by another search within seconds; starting
# HTTP hydration in that gap makes later searches contend for CPU/network/SQLite
# resources and produces the characteristic 'first searches fast, later searches
# slow' pattern. This is a generic scheduler guard, not a product exception.
_SEARCH_IDLE_GRACE_SECONDS = 8.0
_LAST_FOREGROUND_SEARCH_FINISHED = 0.0
_LAST_FOREGROUND_SEARCH_LOCK = threading.Lock()


def _foreground_search_idle_grace_active():
    with _LAST_FOREGROUND_SEARCH_LOCK:
        finished = float(_LAST_FOREGROUND_SEARCH_FINISHED or 0.0)
    return finished > 0.0 and (time.monotonic() - finished) < _SEARCH_IDLE_GRACE_SECONDS


def _mark_foreground_search_finished():
    global _LAST_FOREGROUND_SEARCH_FINISHED
    with _LAST_FOREGROUND_SEARCH_LOCK:
        _LAST_FOREGROUND_SEARCH_FINISHED = time.monotonic()


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


def _fts_query_for_token_sets(token_sets):
    """Build one FTS5 OR query for alternative token sets."""
    groups = []
    for token_set in token_sets:
        part = _fts_query_for_tokens(token_set)
        if part:
            groups.append('(' + part + ')')
    return ' OR '.join(groups)

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


def _seed_sitemaps(store, progress_callback=None):
    """Collect sitemap roots while exposing progress for each robots.txt request.

    A store must never remain indefinitely at the generic discovery_started
    marker: persist which host is being checked and the result of each request.
    """
    roots = []
    robots_diagnostics = []
    bases = _discovery_bases(store)
    for index, base in enumerate(bases, 1):
        base = base.rstrip('/')
        roots.extend(_standard_sitemap_roots(base))
        robots_url = base + '/robots.txt'
        if progress_callback:
            progress_callback(
                f'phase=robots;host={urllib.parse.urlparse(base).netloc};'
                f'host_index={index};host_total={len(bases)};state=requesting'
            )
        try:
            resp = _http_fetch(robots_url, timeout=(3.05, 5.0))
            diagnostic = _diagnostic(resp, robots_url)
            robots_diagnostics.append(diagnostic)
            if resp['status'] < 400 and resp['data']:
                text = resp['data'].decode('utf-8', 'ignore')
                for raw in re.findall(r'(?im)^\s*sitemap\s*:\s*(\S+)', text):
                    raw = raw.strip().strip('<>')
                    if raw:
                        roots.append(urllib.parse.urljoin(robots_url, raw))
        except Exception as exc:
            diagnostic = f'{type(exc).__name__}:{exc}'
            robots_diagnostics.append(diagnostic)
        if progress_callback:
            progress_callback(
                f'phase=robots;host={urllib.parse.urlparse(base).netloc};'
                f'host_index={index};host_total={len(bases)};state=complete;'
                f'result={diagnostic[:180]}'
            )
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
    """Persist discovered URLs in bounded transactions with durable progress.

    A failed batch leaves previously committed batches available for recovery;
    the existing catalog is never deactivated before new URLs are persisted.
    Easycosmetic is restricted to its Belgian storefront at this boundary too,
    so URLs collected from a redirect or stale source cannot enter the BE index.
    """
    if store == 'easycosmetic':
        allowed_hosts = {urllib.parse.urlparse(x).netloc.lower() for x in _discovery_bases(store)}
        product_urls = {
            url: lastmod for url, lastmod in product_urls.items()
            if urllib.parse.urlparse(url).scheme in ('http', 'https')
            and urllib.parse.urlparse(url).netloc.lower() in allowed_hosts
        }

    new_count = len(product_urls)
    old_count = _existing_count(store)

    # Never replace a known catalog with a suspiciously tiny transient result.
    if old_count >= MIN_REPLACEMENT_ABSOLUTE and new_count < old_count * MIN_REPLACEMENT_RATIO:
        detail = (
            f'partial_catalog_rejected;old={old_count};new={new_count};'
            f'visited={diagnostics["visited"]};successes={diagnostics["successes"]};'
            f'entries={diagnostics["entries"]};errors={diagnostics["errors"]}'
        )
        _set_sync_state(store, 'DISCOVERY_PARTIAL', started_at=started_at,
                        finished_at=time.time(), discovered_count=new_count,
                        fetched_count=0, error=detail)
        return 'DISCOVERY_PARTIAL', new_count, detail

    if not new_count:
        detail = (
            f'no_product_urls;visited={diagnostics["visited"]};'
            f'successes={diagnostics["successes"]};entries={diagnostics["entries"]};'
            f'errors={diagnostics["errors"]}'
        )
        _set_sync_state(store, 'DISCOVERY_EMPTY', started_at=started_at,
                        finished_at=time.time(), discovered_count=0,
                        fetched_count=0, error=detail)
        return 'DISCOVERY_EMPTY', 0, detail

    # Preserve the previous active catalog until all incoming batches have
    # committed. Easycosmetic is incremental: deactivate only known German-host
    # rows; do not invalidate valid Belgian rows omitted by a partial sitemap.
    if store not in ('deloox', 'sabina', 'easycosmetic'):
        conn = db()
        try:
            conn.execute('UPDATE store_urls SET active=0 WHERE store=?', (store,))
            conn.commit()
        finally:
            conn.close()

    items = list(product_urls.items())
    batch_size = 250
    persisted = 0
    queued = 0
    try:
        for offset in range(0, len(items), batch_size):
            batch = items[offset:offset + batch_size]
            batch_now = time.time()
            conn = db()
            try:
                with conn:
                    for url, lastmod in batch:
                        conn.execute(
                            """INSERT INTO store_urls(store,url,slug,lastmod,discovered_at,active)
                               VALUES(?,?,?,?,?,1)
                               ON CONFLICT(store,url) DO UPDATE SET
                               slug=excluded.slug,lastmod=excluded.lastmod,
                               discovered_at=excluded.discovered_at,active=1""",
                            (store, url, url_slug(url), lastmod, batch_now),
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
                            (store, url, 'PENDING', 0, batch_now, batch_now, batch_now),
                        )
                persisted += len(batch)
                queued += len(batch)
            finally:
                conn.close()

            progress = (
                f'phase=persist;discovered={new_count};saved={persisted};'
                f'queued={queued};batch_size={len(batch)};'
                f'elapsed_sec={round(time.time() - started_at, 1)}'
            )
            _set_sync_state(store, 'DISCOVERY_RUNNING', started_at=started_at,
                            discovered_count=new_count, fetched_count=persisted,
                            error=progress)

        if store == 'easycosmetic':
            conn = db()
            try:
                conn.execute(
                    "UPDATE store_urls SET active=0 WHERE store=? "
                    "AND lower(url) LIKE '%easycosmetic.de%'",
                    (store,),
                )
                conn.commit()
            finally:
                conn.close()

    except Exception as exc:
        detail = (
            f'persist_failed;discovered={new_count};saved={persisted};queued={queued};'
            f'error={type(exc).__name__}:{exc}'
        )
        try:
            _set_sync_state(store, 'DISCOVERY_PARTIAL', started_at=started_at,
                            finished_at=time.time(), discovered_count=new_count,
                            fetched_count=persisted, error=detail)
        except Exception:
            pass
        return 'DISCOVERY_PARTIAL', persisted, detail

    detail = f'persist_complete;discovered={new_count};saved={persisted};queued={queued}'
    _set_sync_state(store, 'DISCOVERY_OK', started_at=started_at,
                    finished_at=time.time(), discovered_count=new_count,
                    fetched_count=persisted, error=detail)
    if store == 'deloox':
        _sync_deloox_search_index(product_urls)
    return 'DISCOVERY_OK', new_count, detail


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


def _secondary_store_parser(store, final_url, original_url, html_data=None):
    """Run the retailer scraper's exact product-page parser.

    A store parser, when available, is authoritative for extracting the
    retailer's own price/identity semantics. The generic catalog parser is
    only a fallback for stores that do not expose a product-page parser.
    """
    module = importlib.import_module(f'scrapers.{store}.scraper')

    parser = getattr(module, 'extract_product_page', None)
    if callable(parser):
        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})
        try:
            # Some retailer adapters accept the HTML already fetched by
            # refresh_url(). Reuse it when supported so price/variant data
            # comes from the same response and no second page request occurs.
            parameters = inspect.signature(parser).parameters
            # Keep the originally requested URL as the parser's identity URL.
            # Retailers can redirect a variant URL (?variant=123) to the
            # canonical product path while serving the selected variant HTML.
            # Passing only final_url loses that ID, which can attach the
            # default bottle size/offer to every variant in the catalog.
            parser_url = original_url or final_url
            parser_slug = url_slug(parser_url)
            if 'html' in parameters and html_data is not None:
                html_text = html_data.decode('utf-8', errors='replace') if isinstance(html_data, bytes) else str(html_data)
                parsed = parser(session, parser_url, parser_slug, html=html_text)
            else:
                parsed = parser(session, parser_url, parser_slug)
        finally:
            session.close()
    else:
        # ParfumZentrum's current scraper exposes its exact-URL product parser
        # as _extract_product(query). Keep this generic for any store adapter
        # that provides the same callable contract, without embedding store-
        # specific product names, prices or rules in the catalog engine.
        parser = getattr(module, '_extract_product', None)
        if not callable(parser):
            return None
        # Retailer product URLs may append an internal SKU (for example,
        # "_z1016707") that is not part of the product name. Do not pass that
        # identifier into the name matcher as a required query token.
        parser_url = original_url or final_url
        parser_query = re.sub(r'\bz\d+\s*$', '', url_slug(parser_url), flags=re.I).strip()
        parsed = parser(parser_url, parser_query)

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
        'url': parsed.get('url') or original_url or final_url,
        'name': parsed.get('name') or parsed.get('title') or '',
        'brand': parsed.get('brand') or '',
        'image': parsed.get('image') or (parsed.get('source') or {}).get('image'),
        'sku': parsed.get('sku') or identity_value('sku') or '',
        'gtin': parsed.get('gtin') or identity_value('gtin') or '',
        'mpn': parsed.get('mpn') or identity_value('mpn') or '',
        'size_ml': parsed.get('size_ml'),
        'concentration': parsed.get('concentration'),
        'gender': parsed.get('gender'),
        'price_num': price,
        'price': price,
        'currency': parsed.get('currency') or offer.get('currency') or 'EUR',
        'availability': parsed.get('availability') or offer.get('availability') or 'unknown',
        'available': parsed.get('available'),
        'fetched_at': time.time(),
    }


def refresh_url(store, url):
    try:
        # Easycosmetic can stall on variant pages; keep this store's refresh
        # bounded so a slow variant does not hold the whole search response.
        store_timeout = min(6, REFRESH_TIMEOUT) if store == 'easycosmetic' else REFRESH_TIMEOUT
        status, final, data = http_get(url, timeout=store_timeout)
        if status >= 400:
            raise RuntimeError(f'HTTP {status}')

        # The retailer scraper owns retailer-specific product-page semantics
        # such as public-vs-code pricing and product-vs-set identity. When a
        # store exposes that parser, it must run before the generic JSON-LD
        # fallback; otherwise the generic parser can persist a syntactically
        # valid but semantically wrong offer.
        item = None
        secondary_ok = False
        parser_available = False
        try:
            module = importlib.import_module(f'scrapers.{store}.scraper')
            parser_available = callable(getattr(module, 'extract_product_page', None)) or callable(getattr(module, '_extract_product', None))
        except Exception:
            parser_available = False

        if parser_available:
            item = _secondary_store_parser(store, final, url, html_data=data)
            secondary_ok = bool(item and item.get('name'))
        else:
            item = parse_product(store, final, data)

        primary_ok = bool(item and item.get('name'))
        if item and store in ('easycosmetic', 'parfumzentrum'):
            print(
                'CATALOG OFFER DIAG ' +
                f"store={store} url={url!r} final_url={final!r} " +
                f"name={item.get('name')!r} size_ml={item.get('size_ml')!r} " +
                f"price_num={item.get('price_num')!r} price={item.get('price')!r} " +
                f"availability={item.get('availability')!r} available={item.get('available')!r} " +
                f"sku={item.get('sku')!r} gtin={item.get('gtin')!r} " +
                f"parser={'retailer' if secondary_ok else 'generic'}",
                flush=True,
            )

        if item and store == 'parfumzentrum':
            # ParfumZentrum may expose placeholder prices (notably 1.00 EUR)
            # for products that are not actually offered for sale. Never mark
            # such a page as a successfully hydrated, publishable offer.
            raw_price = item.get('price_num')
            if raw_price is None:
                raw_price = item.get('price')
            try:
                parsed_price = float(raw_price)
            except (TypeError, ValueError):
                parsed_price = 0.0
            if parsed_price <= 1.0:
                raise RuntimeError(
                    f'invalid_placeholder_price;store={store};price={raw_price!r}'
                )

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
                size_ml=COALESCE(excluded.size_ml,store_products.size_ml),
                concentration=COALESCE(excluded.concentration,store_products.concentration),
                gender=COALESCE(excluded.gender,store_products.gender),
                price=excluded.price,currency=excluded.currency,
                availability=excluded.availability,fetched_at=excluded.fetched_at,
                fetch_status=excluded.fetch_status''',
            (
                store, url, item.get('name'), item.get('brand'), item.get('image'),
                item.get('sku'), item.get('gtin'), item.get('mpn'),
                item.get('size_ml'), item.get('concentration'), item.get('gender'),
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
        # A ParfumZentrum placeholder price is not a transient network/parser
        # failure: this URL must stop participating in public search and the
        # hydration queue. Other failures remain retryable as before.
        placeholder_offer = (
            store == 'parfumzentrum'
            and 'invalid_placeholder_price' in str(exc)
        )
        if placeholder_offer:
            conn.execute(
                "UPDATE store_urls SET active=0 WHERE store=? AND url=?",
                (store, url),
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



# Stale Easycosmetic records from older catalog versions may have a valid
# product name/price but no parsed size. Repair only matched rows in the
# background so the foreground search latency remains unchanged.
_EASYCOSMETIC_REPAIR_LOCK = threading.Lock()
_EASYCOSMETIC_REPAIR_IN_FLIGHT = set()


def _schedule_easycosmetic_missing_size_repairs(rows):
    jobs = []
    for row in rows or []:
        if str(row.get('store_key') or '').strip().lower() != 'easycosmetic':
            continue
        if row.get('_needs_refresh') or row.get('size_ml') not in (None, '', 0):
            continue
        url = str(row.get('url') or '').strip()
        if not url or 'easycosmetic.' not in url.lower():
            continue
        jobs.append(('easycosmetic', url))

    if not jobs:
        return

    for store, url in jobs:
        key = (store, url)
        with _EASYCOSMETIC_REPAIR_LOCK:
            if key in _EASYCOSMETIC_REPAIR_IN_FLIGHT:
                continue
            _EASYCOSMETIC_REPAIR_IN_FLIGHT.add(key)

        def _repair(target_store=store, target_url=url, target_key=key):
            try:
                result = refresh_url(target_store, target_url)
                if result:
                    print(
                        'CATALOG BACKGROUND REPAIR OK '
                        f'store={target_store} url={target_url} '
                        f"size_ml={result.get('size_ml')} price={result.get('price_num')}",
                        flush=True,
                    )
                else:
                    print(
                        f'CATALOG BACKGROUND REPAIR FAILED store={target_store} url={target_url}',
                        flush=True,
                    )
            except Exception as exc:
                print(
                    f'CATALOG BACKGROUND REPAIR ERROR store={target_store} '
                    f'url={target_url} error={type(exc).__name__}',
                    flush=True,
                )
            finally:
                with _EASYCOSMETIC_REPAIR_LOCK:
                    _EASYCOSMETIC_REPAIR_IN_FLIGHT.discard(target_key)

        threading.Thread(target=_repair, name='easycosmetic-catalog-repair', daemon=True).start()


def search_local(query, per_store=32, search_terms=None, cancel_event=None, deadline=None):
    """Run fast local search; repair legacy Easycosmetic size gaps asynchronously."""
    try:
        rows = _search_local_impl(
            query,
            per_store=per_store,
            search_terms=search_terms,
            cancel_event=cancel_event,
            deadline=deadline,
        )
        _schedule_easycosmetic_missing_size_repairs(rows)
        return rows
    finally:
        _mark_foreground_search_finished()


def _search_local_impl(query, per_store=32, search_terms=None, cancel_event=None, deadline=None):
    """Generate bounded local-catalog candidates using retailer-scoped FTS queries."""
    _diag_t0 = time.monotonic()
    _diag_stage = _diag_t0
    print(f"CATALOG SEARCH DIAG START query={str(query)[:100]!r}", flush=True)

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
        if ts and ts not in token_sets:
            token_sets.append(ts)
    if not token_sets:
        return []

    _diag_tokenized = time.monotonic()
    print(f"CATALOG SEARCH DIAG tokenize={_diag_tokenized-_diag_stage:.3f}s terms={len(token_sets)}", flush=True)
    _diag_stage = time.monotonic()
    conn = _search_db()
    _diag_opened = time.monotonic()
    print(f"CATALOG SEARCH DIAG db_open={_diag_opened-_diag_stage:.3f}s", flush=True)

    rows = []
    unlimited = per_store is None or int(per_store) <= 0
    limit = None if unlimited else max(1, int(per_store))
    total_scan_budget = 2048 if limit is None else max(256, min(2048, limit * 16))
    term_candidate_limit = max(
        8, min(64, max(1, total_scan_budget // max(1, len(token_sets))))
    )
    fts_candidate_limit = max(term_candidate_limit, min(256, term_candidate_limit * 4))

    def interrupted():
        return (
            (cancel_event is not None and cancel_event.is_set())
            or (deadline is not None and time.monotonic() >= float(deadline))
        )

    sql = """
        SELECT u.url AS url,
               u.slug AS slug,
               u.lastmod AS lastmod,
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
               p.fetch_status AS fetch_status,
               f.store AS fts_store
          FROM catalog_search_fts f
          JOIN store_urls u
            ON u.store=f.store AND u.url=f.url
          LEFT JOIN store_products p
            ON p.store=u.store AND p.url=u.url
           AND p.fetch_status='OK'
           AND (p.store != 'parfumzentrum' OR p.price > 1.0)
         WHERE catalog_search_fts MATCH ?
           AND f.store=?
           AND u.active=1
         ORDER BY rank
         LIMIT ?
    """

    try:
        _diag_stage = time.monotonic()
        fts_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_search_fts'"
        ).fetchone()
        print(f"CATALOG SEARCH DIAG fts_check={time.monotonic()-_diag_stage:.3f}s exists={bool(fts_exists)}", flush=True)
        if not fts_exists:
            return _search_local_legacy_sql(
                conn, token_sets, limit, rows,
                cancel_event=cancel_event, deadline=deadline,
            )

        conn.set_progress_handler(lambda: 1 if interrupted() else 0, 1000)

        # Keep FTS ranking and LIMIT inside each retailer. This avoids the costly
        # global ROW_NUMBER window while ensuring every configured retailer,
        # including Deloox, receives its own candidate budget.
        for store in STORES:
            if interrupted():
                break
            for ts in token_sets:
                if interrupted():
                    break
                per_store_counts = {}
                seen_product_keys = set()
                fts_query = _fts_query_for_tokens(ts)
                if not fts_query:
                    continue
                _diag_sql_t0 = time.monotonic()
                try:
                    candidates = conn.execute(
                        sql, (fts_query, store, fts_candidate_limit)
                    ).fetchall()
                except sqlite3.OperationalError:
                    if interrupted():
                        break
                    raise
                _diag_sql_elapsed = time.monotonic() - _diag_sql_t0
                _diag_process_t0 = time.monotonic()
                for r in candidates:
                    if interrupted():
                        break
                    actual_store = str(r['fts_store'] or r['product_store'] or '').strip()
                    if actual_store != store:
                        continue
                    if per_store_counts.get(store, 0) >= term_candidate_limit:
                        continue
                    url = str(r['url'] or '').strip()
                    if not url:
                        continue
                    search_text = ' '.join(
                        str(r[key] or '')
                        for key in ('slug', 'product_name', 'product_brand')
                    )
                    normalized_tokens = set(norm(search_text).split())
                    if not all(token in normalized_tokens for token in ts):
                        continue
                    product_key = (
                        str(r['product_sku'] or '').strip().lower()
                        or str(r['product_gtin'] or '').strip().lower()
                        or str(r['product_mpn'] or '').strip().lower()
                        or url.lower()
                    )
                    if product_key in seen_product_keys:
                        continue
                    seen_product_keys.add(product_key)
                    per_store_counts[store] = per_store_counts.get(store, 0) + 1
                    if r['product_name']:
                        rows.append({
                            'url': url, 'slug': r['slug'] or '',
                            'lastmod': r['lastmod'] or '',
                            'name': r['product_name'] or '',
                            'brand': r['product_brand'] or '',
                            'image': r['product_image'] or '',
                            'sku': r['product_sku'] or '',
                            'gtin': r['product_gtin'] or '',
                            'mpn': r['product_mpn'] or '',
                            'size_ml': r['product_size_ml'],
                            'concentration': r['product_concentration'] or '',
                            'gender': r['product_gender'] or '',
                            'price': r['product_price'],
                            'currency': r['product_currency'] or '',
                            'availability': r['product_availability'] or '',
                            'fetched_at': r['product_fetched_at'],
                            'fetch_status': r['fetch_status'] or 'OK',
                            'price_num': r['product_price'],
                            'store': STORE_LABELS[store],
                            'store_key': store,
                        })
                    else:
                        rows.append({
                            'store': STORE_LABELS[store], 'store_key': store,
                            'url': url, 'name': r['slug'] or url_slug(url),
                            '_needs_refresh': True,
                        })
                print(
                    f"CATALOG SEARCH DIAG store={store} term={str(ts)!r} "
                    f"sql={_diag_sql_elapsed:.3f}s process={time.monotonic()-_diag_process_t0:.3f}s "
                    f"fetched={len(candidates)} rows={len(rows)}",
                    flush=True,
                )

        print(f"CATALOG SEARCH DIAG total={time.monotonic()-_diag_t0:.3f}s rows={len(rows)}", flush=True)
        return rows
    finally:
        try:
            conn.set_progress_handler(None, 0)
        except Exception:
            pass
        conn.close()

def _search_local_legacy_sql(conn, token_sets, limit, rows, cancel_event=None, deadline=None):
    # Compatibility path for SQLite builds without FTS5.
    for store in STORES:
        if cancel_event is not None and cancel_event.is_set():
            break
        if deadline is not None and time.monotonic() >= float(deadline):
            break

        selected_by_url = {}
        for ts in token_sets:
            if cancel_event is not None and cancel_event.is_set():
                break
            if deadline is not None and time.monotonic() >= float(deadline):
                break
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

            sql = f"""
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
                   AND (p.store != 'parfumzentrum' OR p.price > 1.0)
                 WHERE u.store=? AND u.active=1
                   AND {' AND '.join(clauses)}
                 LIMIT ?
            """
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


def _queue_release_claim(task):
    """Return a claimed hydration task to PENDING without recording an error."""
    now = time.time()
    conn = db()
    try:
        with conn:
            conn.execute(
                """UPDATE hydration_queue
                   SET state='PENDING',
                       leased_until=NULL,
                       lease_token=NULL,
                       available_at=?,
                       last_error=NULL
                 WHERE store=? AND url=? AND lease_token=?
                   AND state='PROCESSING'""",
                (now, task['store'], task['url'], task['lease_token']),
            )
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

        # 404/410, known ParfumZentrum placeholder prices and exhausted
        # retries are terminal. Placeholder offers are deactivated by
        # refresh_url(); do not retry them as if they were transient failures.
        terminal_http = http_status in (404, 410)
        terminal_placeholder = 'invalid_placeholder_price' in str(error)
        next_state = (
            'DEAD'
            if terminal_http or terminal_placeholder or attempts >= HYDRATION_MAX_ATTEMPTS
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
    """Execute one claimed page fetch and transition its queue state.

    Foreground search has strict priority. A task that was claimed just before
    a search started is released instead of performing another HTTP fetch.
    """
    if _foreground_search_running():
        _queue_release_claim(task)
        return None

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
        if _foreground_search_running():
            break
        if deadline is not None and time.monotonic() >= float(deadline):
            break
        task = _claim_one_hydration_task()
        if not task:
            break
        tasks.append(task)

    if not tasks:
        return {'selected': 0, 'fetched': 0, 'errors': 0}

    if _foreground_search_running():
        for task in tasks:
            _queue_release_claim(task)
        return {'selected': 0, 'fetched': 0, 'errors': 0}

    fetched = 0
    errors = 0
    pool = ThreadPoolExecutor(max_workers=min(worker_count, len(tasks)))
    futures = [pool.submit(_hydrate_one_task, task) for task in tasks]
    try:
        for future in as_completed(futures):
            try:
                result = future.result()
                if result is True:
                    fetched += 1
                elif result is False:
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
_COVERAGE_TASK_TIMEOUT_SECONDS = 30.0
_COVERAGE_CANCEL_POLL_SECONDS = 0.25
_COVERAGE_CANCEL_EVENT = threading.Event()


def _foreground_search_running():
    """Return True while the normal foreground search job is running.

    The catalog hydration/coverage worker is deliberately lower priority than
    user searches.  Foreground jobs are named by main.py with the stable
    `scenthunter-search-` prefix.  When one is active, background scraper work
    must not start, because it can otherwise consume CPU/network time and
    contend with the foreground matcher even though the public search itself
    is catalog-only.
    """
    try:
        return any(
            thread.is_alive()
            and str(thread.name or '').startswith('scenthunter-search-')
            for thread in threading.enumerate()
        )
    except Exception:
        return False

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
    """Accept only official hosts configured for this retailer.

    DISCOVERY_BASES is the source of truth for localized storefronts. Keep
    www/non-www aliases for each configured official host, while preserving
    the existing base-host behavior for stores without explicit discovery
    bases. URL paths and query parameters (including selected variants) are
    intentionally preserved.
    """
    if not raw_url:
        return ''
    try:
        url = urllib.parse.urljoin(STORES.get(store, ''), str(raw_url)).split('#', 1)[0]
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return ''
        # Do not allow credential-bearing URLs to pass host validation.
        if parsed.username is not None or parsed.password is not None:
            return ''
        host = parsed.hostname.lower().rstrip('.')
        base_host = urllib.parse.urlparse(STORES.get(store, '')).hostname
        allowed = set()
        if base_host:
            base_host = base_host.lower().rstrip('.')
            allowed.update({
                base_host,
                base_host[4:] if base_host.startswith('www.') else 'www.' + base_host,
            })
        for base in DISCOVERY_BASES.get(store, ()):
            try:
                configured_host = urllib.parse.urlparse(base).hostname
            except Exception:
                configured_host = None
            if configured_host:
                configured_host = configured_host.lower().rstrip('.')
                allowed.add(configured_host)
                allowed.add(
                    configured_host[4:]
                    if configured_host.startswith('www.')
                    else 'www.' + configured_host
                )
        return url if host in allowed else ''
    except Exception:
        return ''


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


def _coverage_scraper_process(
    module_name,
    queries,
    timeout_seconds=_COVERAGE_TASK_TIMEOUT_SECONDS,
    cancel_event=None,
):
    """Run one retailer coverage search in a killable process group.

    A foreground user search has priority over background catalog coverage.
    The child process is therefore polled instead of using communicate(timeout),
    so an already-running coverage task can be terminated as soon as a
    foreground search starts.
    """
    child_code = 'import contextlib\nimport importlib\nimport json\nimport sys\n\ndef main():\n    payload = json.load(sys.stdin)\n    module_name = str(payload.get("module") or "")\n    queries = payload.get("queries") or []\n    module = importlib.import_module(module_name)\n    search_stream = getattr(module, "search_stream", None)\n    search_fn = getattr(module, "search", None)\n    if not callable(search_stream) and not callable(search_fn):\n        raise RuntimeError("scraper_search_unavailable")\n    reports = []\n    for query in queries:\n        try:\n            with contextlib.redirect_stdout(sys.stderr):\n                report = search_stream(query) if callable(search_stream) else search_fn(query)\n            reports.append({"query": query, "report": report})\n        except Exception as exc:\n            reports.append({"query": query, "error": f"{type(exc).__name__}:{exc}"})\n            continue\n        if isinstance(report, dict):\n            if report.get("results"):\n                break\n        elif isinstance(report, list) and report:\n            break\n    json.dump({"ok": True, "reports": reports}, sys.stdout, ensure_ascii=False, default=str)\n    sys.stdout.flush()\n\nif __name__ == "__main__":\n    main()\n'
    payload = json.dumps({"module": module_name, "queries": list(queries)}, ensure_ascii=False)
    env = os.environ.copy()
    current_python_path = env.get("PYTHONPATH", "")
    base_path = str(BASE_DIR)
    env["PYTHONPATH"] = base_path + (os.pathsep + current_python_path if current_python_path else "")
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", child_code],
            cwd=str(BASE_DIR), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=(os.name != "nt"),
        )
    except Exception as exc:
        return {"ok": False, "reports": [], "error": f"{type(exc).__name__}:{exc}"}
    try:
        process.stdin.write(payload)
        process.stdin.close()
        deadline = time.monotonic() + float(timeout_seconds)
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                try:
                    if os.name != "nt": os.killpg(process.pid, signal.SIGTERM)
                    else: process.terminate()
                except Exception:
                    pass
                try: process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name != "nt": os.killpg(process.pid, signal.SIGKILL)
                        else: process.kill()
                    except Exception:
                        pass
                    try: process.wait(timeout=2.0)
                    except Exception: pass
                return {"ok": False, "cancelled": True, "reports": [], "error": "coverage_cancelled_foreground_search"}
            if _foreground_search_running():
                if cancel_event is not None:
                    cancel_event.set()
                try:
                    if os.name != "nt": os.killpg(process.pid, signal.SIGTERM)
                    else: process.terminate()
                except Exception:
                    pass
                try: process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name != "nt": os.killpg(process.pid, signal.SIGKILL)
                        else: process.kill()
                    except Exception:
                        pass
                    try: process.wait(timeout=2.0)
                    except Exception: pass
                return {"ok": False, "cancelled": True, "reports": [], "error": "coverage_cancelled_foreground_search"}
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired([sys.executable, "-c", child_code], float(timeout_seconds))
            time.sleep(_COVERAGE_CANCEL_POLL_SECONDS)
        stdout = process.stdout.read() if process.stdout is not None else ""
    except subprocess.TimeoutExpired:
        try:
            if os.name != "nt": os.killpg(process.pid, signal.SIGTERM)
            else: process.terminate()
        except Exception: pass
        try: process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                if os.name != "nt": os.killpg(process.pid, signal.SIGKILL)
                else: process.kill()
            except Exception: pass
            try: process.wait(timeout=2.0)
            except Exception: pass
        return {"ok": False, "reports": [], "error": f"coverage_timeout_after_{float(timeout_seconds):g}s"}
    except Exception as exc:
        try:
            if os.name != "nt": os.killpg(process.pid, signal.SIGTERM)
            else: process.terminate()
        except Exception: pass
        try: process.wait(timeout=2.0)
        except Exception: pass
        return {"ok": False, "reports": [], "error": f"{type(exc).__name__}:{exc}"}
    if process.returncode != 0:
        return {"ok": False, "reports": [], "error": f"coverage_process_exit_{process.returncode}"}
    try: result = json.loads(stdout or "")
    except Exception as exc:
        return {"ok": False, "reports": [], "error": f"coverage_invalid_child_output:{type(exc).__name__}:{exc}"}
    return result if isinstance(result, dict) else {"ok": False, "reports": [], "error": "coverage_invalid_child_result"}


def _coverage_run_task(task, cancel_event=None):
    if cancel_event is not None and cancel_event.is_set():
        return {'state': 'CANCELLED', 'found': 0, 'error': 'coverage_cancelled_foreground_search'}
    if _foreground_search_running():
        if cancel_event is not None:
            cancel_event.set()
        return {'state': 'CANCELLED', 'found': 0, 'error': 'coverage_cancelled_foreground_search'}
    store = task['store']
    product = task['product']
    queries = _coverage_queries(product)
    module_name = _COVERAGE_STORE_MODULES.get(store)
    if not module_name:
        return {'state': 'ERROR', 'found': 0, 'error': 'store_module_missing'}
    isolated = _coverage_scraper_process(module_name, queries, cancel_event=cancel_event)
    reports = isolated.get('reports') or []
    if isolated.get('cancelled') or (cancel_event is not None and cancel_event.is_set()):
        return {'state': 'CANCELLED', 'found': 0, 'error': 'coverage_cancelled_foreground_search'}
    if not isolated.get('ok'):
        return {'state': 'RETRY', 'found': 0, 'error': str(isolated.get('error') or 'coverage_process_failed')[:1000]}
    matched_rows = []
    errors = []
    for item in reports:
        if not isinstance(item, dict): continue
        if item.get('error'):
            errors.append(str(item['error'])); continue
        report = item.get('report')
        if isinstance(report, dict):
            rows = report.get('results') or []
            status = str(report.get('status') or '')
            if status in {'error','timeout','blocked','unavailable'}:
                errors.append(str(report.get('error') or status))
        else:
            rows = report if isinstance(report, list) else []
        for row in rows:
            if _coverage_result_matches(product, row): matched_rows.append(row)
    found = _coverage_persist_urls(store, matched_rows)
    if found: return {'state': 'FOUND', 'found': found, 'error': None}
    if errors: return {'state': 'RETRY', 'found': 0, 'error': errors[0][:1000]}
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
                         CASE store WHEN 'deloox' THEN 0 ELSE 1 END,
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
    if state == 'CANCELLED':
        next_run = now + 5.0
        db_state = 'PENDING'
    else:
        next_run = now + (_COVERAGE_RETRY_SECONDS if state in {'FOUND','NOT_FOUND'} else _COVERAGE_ERROR_RETRY_SECONDS)
        db_state = state
    conn = db()
    try:
        conn.execute(
            """UPDATE catalog_coverage
                  SET state=?,found_urls=?,last_finished_at=?,next_run_at=?,last_error=?
                WHERE store=? AND product_id=?""",
            (
                db_state, int(result.get('found') or 0), now, next_run, result.get('error'),
                task['store'], str(task['product'].get('product_id') or ''),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def coverage_batch(max_tasks=_COVERAGE_BATCH_SIZE, workers=_COVERAGE_WORKERS):
    """Advance canonical-product coverage in small bounded batches.

    Coverage is strictly background work. If a foreground search starts,
    already-running coverage children are terminated and their tasks are
    returned to PENDING for a later idle window.
    """
    _COVERAGE_CANCEL_EVENT.clear()
    if _foreground_search_running():
        return {'selected': 0, 'found': 0, 'not_found': 0, 'errors': 0}
    tasks = _coverage_claim_tasks(max_tasks)
    if not tasks:
        return {'selected': 0, 'found': 0, 'not_found': 0, 'errors': 0}
    found = not_found = errors = 0
    worker_count = max(1, min(int(workers), len(tasks), _COVERAGE_WORKERS))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_map = {pool.submit(_coverage_run_task, task, _COVERAGE_CANCEL_EVENT): task for task in tasks}
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
            # Background coverage/hydration is lower priority than the
            # foreground catalog search.  Never start another retailer
            # scraper or hydration batch while a user search is active.
            if _foreground_search_running() or _foreground_search_idle_grace_active():
                if stop_event is not None:
                    stop_event.wait(0.25)
                else:
                    time.sleep(0.25)
                continue

            now_mono = time.monotonic()
            # Canonical coverage is a background catalog-maintenance path,
            # not part of foreground search. It is allowed to run only while
            # the foreground search is idle, and it feeds the same durable
            # store_urls -> hydration pipeline as normal discovery.
            if now_mono >= coverage_next_at and not _foreground_search_running():
                coverage_next_at = now_mono + _COVERAGE_INTERVAL_SECONDS
                coverage = coverage_batch(
                    max_tasks=_COVERAGE_BATCH_SIZE,
                    workers=_COVERAGE_WORKERS,
                )
                if coverage.get('selected', 0) or coverage.get('found', 0) or coverage.get('errors', 0):
                    print(
                        'CATALOG COVERAGE BATCH '
                        f"selected={coverage.get('selected')} "
                        f"found={coverage.get('found')} "
                        f"not_found={coverage.get('not_found')} "
                        f"errors={coverage.get('errors')}",
                        flush=True,
                    )

            if _foreground_search_running() or _foreground_search_idle_grace_active():
                if stop_event is not None:
                    stop_event.wait(0.25)
                else:
                    time.sleep(0.25)
                continue

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

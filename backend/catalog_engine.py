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

import ctypes
import gzip
import html
import heapq
import importlib
import inspect
import json
import re
import sqlite3
import traceback
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
from bs4 import BeautifulSoup, SoupStrainer


def _set_catalog_pool_worker_os_name():
    """Prevent executor threads from inheriting the discovery-active Linux name.

    Linux inherits the creator thread's comm when a new thread is created.
    The family-coverage process scans /proc, so a pool created during discovery
    must not retain the discovery marker after the main crawl thread goes idle.
    """
    try:
        encoded = b"sh-catalog-work"
        result = ctypes.CDLL(None, use_errno=True).prctl(
            15, ctypes.c_char_p(encoded), 0, 0, 0
        )
        if result != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_NAME) failed")
    except Exception as exc:
        print(
            "CATALOG POOL OS THREAD NAME ERROR "
            f"error={type(exc).__name__}:{exc}",
            flush=True,
        )

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
    'easycosmetic': (
        # ScentHunter uses the German market: discover German URLs only.
        'https://www.easycosmetic.de',
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
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.7',
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

# Store-wide HTML discovery entry points supplement incomplete sitemaps.
# These are generic retailer navigation surfaces, not product-specific URLs.
HTML_DISCOVERY_SEEDS = {
    'easycosmetic': (
        # Official German fragrance catalog surfaces. These let the generic
        # HTML crawler recover product URLs when the retailer sitemap is
        # unavailable or does not expose product pages.
        'https://www.easycosmetic.de/',
        'https://www.easycosmetic.de/parfum',
        'https://www.easycosmetic.de/damenparfum',
        'https://www.easycosmetic.de/herrenparfum',
    ),
    'parfumzentrum': (
        'https://www.parfum-zentrum.de/',
        'https://www.parfum-zentrum.de/parfum_k319/',
        # Retailer brand index for Rasasi; this is a brand-level catalog page,
        # not a product-specific URL or matching exception.
        'https://www.parfum-zentrum.de/rasasi_v829/parfum_k319/',
        # Generic men's-fragrance subcategory for the Rasasi brand catalog.
        # This is a navigation surface, not a product-specific URL.
        'https://www.parfum-zentrum.de/rasasi_v829/parfum_k319/herrendufte_k322/',
    ),
    'sabina': (
        'https://www.sabina.com/',
        'https://www.sabina.com/es/buscar?search_query=parfum',
        'https://www.sabina.com/it/ricerca_old?s=parfum',
        'https://www.sabina.com/it/ricerca_old?s=extrait',
    ),
    'deloox': (
        'https://www.deloox.be/',
        'https://www.deloox.com/en/search?q=perfume',
    ),
}

# Bounded HTML discovery settings used by the generic crawler and Deloox frontier.
HTML_MAX_PAGES = 800
HTML_MAX_DEPTH = 8
HTML_WORKERS = 12
DELOOX_SEARCH_MAX_PAGES = 10
DELOOX_GENERIC_CATALOG_QUERIES = (
    'parfum',
    'perfume',
    'fragrance',
)

DISCOVERY_HARD_TIMEOUT = 300
SITEMAP_DISCOVERY_BUDGET = 45
HTML_FALLBACK_SITEMAP_PRODUCT_THRESHOLD = 100

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

# A failed refresh must not destroy the last known-good offer. Keep the most
# recent attempt error separately so the hydration queue can record the real
# failure while store_products continues to represent the last successful fetch.
_LAST_REFRESH_ERRORS = {}
_LAST_REFRESH_ERRORS_LOCK = threading.Lock()

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
        # Multiple retailer bottle sizes can share one canonical product URL.
        # Keep URL-level hydration/FTS intact and store each offer independently.
        conn.execute("""CREATE TABLE IF NOT EXISTS store_product_variants(
            store TEXT NOT NULL, url TEXT NOT NULL, variant_key TEXT NOT NULL,
            name TEXT, brand TEXT, image TEXT, sku TEXT, gtin TEXT, mpn TEXT,
            size_ml REAL, concentration TEXT, gender TEXT, price REAL, currency TEXT,
            availability TEXT, fetched_at REAL, variant_url TEXT,
            PRIMARY KEY(store,url,variant_key))""")
        # Migrate existing catalogs in place: retailer variant URLs are distinct
        # from the canonical product URL (e.g. Sabina's #/dimensione-100_ml).
        variant_columns = {row['name'] for row in conn.execute(
            'PRAGMA table_info(store_product_variants)'
        ).fetchall()}
        if 'variant_url' not in variant_columns:
            conn.execute('ALTER TABLE store_product_variants ADD COLUMN variant_url TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_store_product_variants_store_size ON store_product_variants(store,size_ml)')
        _ensure_search_fts(conn)
        conn.execute("""CREATE TABLE IF NOT EXISTS sync_state(
            store TEXT PRIMARY KEY, status TEXT, started_at REAL, finished_at REAL,
            discovered_count INTEGER DEFAULT 0, fetched_count INTEGER DEFAULT 0, error TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hydration_queue(
            store TEXT NOT NULL,
            url TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'PENDING',
            priority INTEGER NOT NULL DEFAULT 100,
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
        hydration_columns = {
            row['name'] for row in conn.execute('PRAGMA table_info(hydration_queue)').fetchall()
        }
        if 'priority' not in hydration_columns:
            conn.execute(
                'ALTER TABLE hydration_queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 100'
            )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hydration_ready ON hydration_queue(state,available_at,store)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_hydration_ready_priority ON hydration_queue(store,state,priority,attempts,available_at,first_seen_at)')
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
    conn = sqlite3.connect(DB_PATH, timeout=45)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=45000')
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
    """Persist discovered URLs in bounded transactions.

    Easycosmetic is incremental: valid German URLs omitted by a partial
    discovery run must remain active. Non-German-host rows are deactivated.
    """

    if store == "easycosmetic":
        # German Easycosmetic is the only canonical market for this store.
        # Filter before any counts, guards, persistence, or hydration queuing.
        allowed_hosts = {
            "easycosmetic.de",
            "www.easycosmetic.de",
        }
        filtered_urls = {}
        for url, lastmod in product_urls.items():
            parsed = urllib.parse.urlparse(str(url or ""))
            host = (parsed.hostname or "").lower().rstrip(".")
            if parsed.scheme in ("http", "https") and host in allowed_hosts:
                filtered_urls[url] = lastmod
        product_urls = filtered_urls

        conn = db()
        try:
            # Validate the actual URL hostname instead of substring-matching
            # SQL. This retires legacy/non-German URLs without allowing a URL
            # that merely contains "easycosmetic.de" in its path or query.
            rows = conn.execute(
                "SELECT url FROM store_urls WHERE store='easycosmetic'"
            ).fetchall()
            invalid_urls = []
            for row in rows:
                stored_url = str(row[0] or "")
                parsed = urllib.parse.urlparse(stored_url)
                host = (parsed.hostname or "").lower().rstrip(".")
                if parsed.scheme not in ("http", "https") or host not in allowed_hosts:
                    invalid_urls.append(stored_url)

            if invalid_urls:
                with conn:
                    conn.executemany(
                        "UPDATE store_urls SET active=0 WHERE store='easycosmetic' AND url=?",
                        ((url,) for url in invalid_urls),
                    )
                    conn.executemany(
                        "DELETE FROM catalog_search_fts WHERE store='easycosmetic' AND url=?",
                        ((url,) for url in invalid_urls),
                    )
        finally:
            conn.close()

    now = time.time()

    new_count = len(product_urls)
    old_count = _existing_count(store)

    if (
        old_count >= MIN_REPLACEMENT_ABSOLUTE
        and new_count < old_count * MIN_REPLACEMENT_RATIO
    ):
        detail = (
            f"partial_catalog_rejected;old={old_count};new={new_count};"
            f'visited={diagnostics["visited"]};successes={diagnostics["successes"]};'
            f'entries={diagnostics["entries"]};errors={diagnostics["errors"]}'
        )
        _set_sync_state(
            store,
            "DISCOVERY_PARTIAL",
            started_at=started_at,
            finished_at=now,
            discovered_count=new_count,
            fetched_count=0,
            error=detail,
        )
        return "DISCOVERY_PARTIAL", new_count, detail

    if not new_count:
        detail = (
            f"no_product_urls;visited={diagnostics['visited']};"
            f"successes={diagnostics['successes']};"
            f"entries={diagnostics['entries']};"
            f"errors={diagnostics['errors']}"
        )
        _set_sync_state(
            store,
            "DISCOVERY_EMPTY",
            started_at=started_at,
            finished_at=now,
            discovered_count=0,
            fetched_count=0,
            error=detail,
        )
        return "DISCOVERY_EMPTY", 0, detail

    items = list(product_urls.items())
    batch_size = 250
    persisted = 0
    queued = 0

    for offset in range(0, len(items), batch_size):
        batch = items[offset:offset + batch_size]
        batch_now = time.time()

        conn = db()
        try:
            with conn:
                for url, lastmod in batch:
                    conn.execute(
                        """INSERT INTO store_urls(
                               store,url,slug,lastmod,discovered_at,active)
                           VALUES(?,?,?,?,?,1)
                           ON CONFLICT(store,url) DO UPDATE SET
                               slug=excluded.slug,
                               lastmod=excluded.lastmod,
                               discovered_at=excluded.discovered_at,
                               active=1""",
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
                                        AND hydration_queue.leased_until > ?
                                   THEN 'PROCESSING'
                                   ELSE hydration_queue.state
                               END""",
                        (store, url, "PENDING", 0, batch_now, batch_now, batch_now, batch_now),
                    )

            persisted += len(batch)
            queued += len(batch)

            progress = (
                f"phase=persist;discovered={new_count};saved={persisted};"
                f"queued={queued};batch_size={len(batch)};"
                f"elapsed_sec={round(time.time() - started_at, 1)}"
            )
            _set_sync_state(
                store,
                "DISCOVERY_RUNNING",
                started_at=started_at,
                discovered_count=new_count,
                fetched_count=persisted,
                error=progress,
            )

        except Exception as exc:
            detail = (
                f"persist_failed;discovered={new_count};saved={persisted};"
                f"queued={queued};error={type(exc).__name__}:{exc}"
            )
            _set_sync_state(
                store,
                "DISCOVERY_PARTIAL",
                started_at=started_at,
                finished_at=now,
                discovered_count=new_count,
                fetched_count=persisted,
                error=detail,
            )
            return "DISCOVERY_PARTIAL", persisted, detail

    detail = f"persist_complete;discovered={new_count};saved={persisted};queued={queued}"
    _set_sync_state(
        store,
        "DISCOVERY_OK",
        started_at=started_at,
        finished_at=now,
        discovered_count=new_count,
        fetched_count=persisted,
        error=detail,
    )

    if store == "deloox":
        _sync_deloox_search_index(product_urls)

    return "DISCOVERY_OK", new_count, detail



def _allowed_store_hosts(store):
    """Return configured official hosts plus their www/non-www aliases."""
    hosts = set()
    for base in _discovery_bases(store):
        hostname = urllib.parse.urlparse(base).hostname
        if not hostname:
            continue
        hostname = hostname.lower().rstrip('.')
        hosts.add(hostname)
        hosts.add(hostname[4:] if hostname.startswith('www.') else 'www.' + hostname)
    return hosts


def _store_allowed_url(store, raw_url, base_url=None):
    """Resolve a canonical catalog URL and enforce the retailer host boundary.

    Product identity/discovery URLs deliberately drop fragments so variants of
    one product do not become separate catalog entries. Do not use this helper
    for customer-facing variant links: fragments can select a specific size.
    """
    absolute = _store_allowed_variant_url(store, raw_url, base_url)
    if not absolute:
        return None
    return absolute.split('#', 1)[0]


def _store_allowed_variant_url(store, raw_url, base_url=None):
    """Resolve an official retailer URL while preserving variant fragments.

    For stores such as Sabina, ``#/dimensione-100_ml`` selects the exact
    commercial variant. Validate the same host/scheme boundary as catalog URLs
    without stripping that fragment.
    """
    if not raw_url:
        return None
    absolute = urllib.parse.urljoin(base_url or STORES.get(store, ''), str(raw_url))
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.hostname.lower().rstrip('.') not in _allowed_store_hosts(store):
        return None
    return absolute



def _sabina_variant_url(raw_url, base_url, size_ml):
    """Return the Spanish Sabina URL for the exact variant."""
    absolute = (
        _store_allowed_variant_url('sabina', raw_url, base_url)
        or _store_allowed_variant_url('sabina', base_url, base_url)
    )
    if not absolute:
        return base_url

    try:
        size = float(str(size_ml).strip().replace(',', '.'))
    except (TypeError, ValueError):
        return absolute

    if size <= 0:
        return absolute

    parsed = urllib.parse.urlparse(absolute)
    if (parsed.hostname or '').lower().rstrip('.') not in {
        'sabina.com', 'www.sabina.com'
    }:
        return absolute

    if not re.match(r'^/es/', parsed.path, re.I):
        normalized_path = re.sub(
            r'^/(?:it|fr|en|de|nl|pt|tw|da|pl)/',
            '/es/',
            parsed.path,
            count=1,
            flags=re.I,
        )
        if not re.match(r'^/es/', normalized_path, re.I):
            return absolute
        parsed = parsed._replace(path=normalized_path)

    # Sabina's variant selector requires the real product-attribute ID, e.g.
    # #/25-tama_o-50_ml. Never synthesize the old /30-Tamano-* fragment:
    # it does not select the requested commercial variant.
    size_label = f"{size:g}".replace('.', '_')
    fragment = (parsed.fragment or '').strip().lstrip('/')
    match = re.fullmatch(r'(\d+)-tama_o-(\d+(?:_\d+)?)_ml', fragment, re.I)
    if match:
        try:
            fragment_size = float(match.group(2).replace('_', '.'))
        except (TypeError, ValueError):
            fragment_size = None
        if fragment_size is not None and abs(fragment_size - size) < 0.01:
            return urllib.parse.urlunparse(parsed._replace(fragment='/' + fragment))

    # If the source URL has no verified combination ID for this size, return
    # the canonical product URL rather than inventing a misleading variant URL.
    return urllib.parse.urlunparse(parsed._replace(fragment=''))



def _html_product_url(store, raw_url, base_url):
    if not raw_url:
        return None
    absolute = _store_allowed_url(store, raw_url, base_url)
    if not absolute:
        return None
    p = urllib.parse.urlparse(absolute)
    path = p.path or '/'
    low = path.lower()
    if store == 'easycosmetic':
        # Product paths can use formats other than .aspx. Restrict to the
        # retailer's approved host (checked above) and exclude utility/category
        # navigation paths, but preserve query parameters such as variant IDs.
        if any(x in low for x in (
            '/suche', '/search', '/service', '/kontakt', '/impressum',
            '/datenschutz', '/agb', '/versand', '/zahlung', '/marken',
            '/alle-marken', '/faq/', '/login', '/account', '/cart',
            '/checkout', '/warenkorb', '/kundenkonto',
        )):
            return None
        if low in ('/', '/parfum', '/damenparfum', '/herrenparfum', '/neuheiten'):
            return None
        if low.endswith(('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.pdf', '.css', '.js')):
            return None
        return absolute
    if store == 'deloox':
        # Product identity is the path. Strip tracking/query parameters so
        # pagination/session parameters never create duplicate catalog rows.
        canonical = urllib.parse.urlunparse((
            p.scheme, p.netloc, p.path, '', '', ''
        ))
        if re.search(r'/(?:product|produit|producto|prodotto)/\d+(?:/|$)', low, re.I):
            return canonical
        if low.endswith('.html') and not re.search(r'/(?:category|categorie|categoria|catégorie|chercher|search|sitemap|brand|marque|marca|login|account|cart|checkout)(?:/|$)', low, re.I):
            return canonical
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
    absolute = _store_allowed_url(store, raw_url, base_url)
    if not absolute:
        return None
    p = urllib.parse.urlparse(absolute)
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
        # Ingredient encyclopaedia pages are not catalog listings and can
        # otherwise keep the durable graph busy without yielding products.
        if re.search(r'/(?:ingredients?|ingredienten|ingr[eé]dients?)(?:/|$)', path, re.I):
            return None
        # The Deloox homepage is the root of the catalog graph.
        if path in ('', '/'):
            return absolute
        # Public search is useful for generic catalog enumeration.
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
        # Sabina's Spanish native search is a generic catalog enumeration
        # surface used by the runtime scraper. Accept it only with the
        # retailer's search_query parameter; discovery never injects the
        # user's request into these URLs. Product pages are excluded here
        # because _html_product_url handles their numeric-id .html shape.
        if path.rstrip('/') == '/es/buscar':
            if re.search(r'(?:^|&)(?:search_query)=', p.query, re.I):
                return absolute
            return None
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
    if store == 'parfumzentrum':
        # ParfumZentrum category URLs encode their navigation IDs in the
        # path (for example /rasasi_v829/parfum_k319/f/herren/). Product URLs
        # are handled separately by _html_product_url and end in _z<digits>.
        # Accept category/facet paths and their pagination variants so the
        # discovery crawler can traverse the retailer's catalog graph.
        if re.search(r'(?:^|_)z\d+/?$', path, re.I):
            return None
        if re.search(r'(?:^|_)v\d+(?:/|$)|(?:^|_)k\d+(?:/|$)', path, re.I):
            return absolute
        if re.search(r'(?:^|&)(?:page|seite|p|offset|start)=', p.query, re.I):
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


def _fetch_html_page(store, url, timeout=HTTP_TIMEOUT):
    """Fetch one HTML page; callers may set a shorter diagnostic timeout."""
    try:
        resp = _http_fetch(url, timeout=timeout)
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
        and path.rstrip('/') == '/es/buscar'
        and re.search(r'(?:^|&)search_query=', p.query, re.I)
    ):
        # The Spanish native search is a high-value catalog surface for Sabina.
        # Priority is structural and independent of the user's query.
        score = 0
    elif (
        store == 'sabina'
        and path.rstrip('/') in ('/it/ricerca_old', '/it/ricerca')
        and re.search(r'(?:^|&)s=', p.query, re.I)
    ):
        score = 0
    # ParfumZentrum encodes brand catalog pages with a generic _v<number>
    # path segment (for example /brand_v123/). Prioritize these brand-level
    # catalog surfaces over broad category branches so a bounded crawl reaches
    # the retailer's brand catalog graph instead of spending its early budget
    # on unrelated categories. The rule is URL-structure-only and applies to
    # every brand; it contains no product name, brand name, or product ID.
    elif (
        store == 'parfumzentrum'
        and re.search(r'/(?:[^/]+_v\d+)(?:/|$)', path, re.I)
        and re.search(r'/(?:herrendufte|herrenduefte|men|male)[^/]*(?:/|$)', path, re.I)
    ):
        # Prefer men's-fragrance subcategories within any retailer brand index
        # over unrelated brand roots. This is generic URL structure, not a
        # named-brand or product exception.
        score = -1
    elif store == 'parfumzentrum' and re.search(r'/(?:[^/]+_v\d+)(?:/|$)', path, re.I):
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
    """Admit official Deloox URLs, excluding only obvious non-fragrance products."""
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
    if p.netloc.lower() not in allowed_hosts:
        return False

    # Existing records are not deleted or mutated here. This admission guard
    # only prevents newly discovered obvious haircare/skincare/makeup pages
    # from being enqueued. Keep ambiguous slugs eligible.
    slug = urllib.parse.unquote(p.path.rsplit('/', 1)[-1]).lower()
    if re.search(
        r"(?:^|[-_ ])(?:shampoo|shampoing|conditioner|apres-shampoing|"
        r"haarmaske|hair-mask|haircare|hair-care|hair-spray|"
        r"styling-cream|molding-cream|skincare|skin-care|face-cream|"
        r"body-lotion|foundation|mascara|eyeliner|lipstick|nail-polish|"
        r"makeup|cosmetics|deodorant|toothpaste|oral-care|shower-gel)"
        r"(?:[-_ ]|\.|$)",
        slug,
        re.I,
    ):
        return False
    return True

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
    """Durably enqueue catalog/navigation URLs with minimal SQLite work.

    Existing DONE rows are not reset by ordinary rediscovery. Avoid a
    per-URL SELECT before the UPSERT: that doubles queue statements and keeps
    a read transaction open while competing catalog workers need the write
    lock. The UPSERT itself only updates rows whose durable metadata changes.
    """
    if not items:
        return 0
    now = time.time()
    conn = db()
    affected = 0
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
                cursor = conn.execute(
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
                           END,
                           state=CASE
                               WHEN excluded.source='configured_seed'
                                    AND catalog_discovery_queue.state IN ('DONE','DEAD')
                               THEN 'PENDING'
                               ELSE catalog_discovery_queue.state
                           END,
                           available_at=CASE
                               WHEN excluded.source='configured_seed'
                                    AND catalog_discovery_queue.state IN ('DONE','DEAD')
                               THEN excluded.available_at
                               ELSE catalog_discovery_queue.available_at
                           END,
                           leased_until=CASE
                               WHEN excluded.source='configured_seed'
                                    AND catalog_discovery_queue.state IN ('DONE','DEAD')
                               THEN NULL
                               ELSE catalog_discovery_queue.leased_until
                           END,
                           lease_token=CASE
                               WHEN excluded.source='configured_seed'
                                    AND catalog_discovery_queue.state IN ('DONE','DEAD')
                               THEN NULL
                               ELSE catalog_discovery_queue.lease_token
                           END,
                           last_error=CASE
                               WHEN excluded.source='configured_seed'
                                    AND catalog_discovery_queue.state IN ('DONE','DEAD')
                               THEN NULL
                               ELSE catalog_discovery_queue.last_error
                           END
                       WHERE catalog_discovery_queue.depth > excluded.depth
                          OR catalog_discovery_queue.priority > excluded.priority
                          OR catalog_discovery_queue.source = ''
                          OR (excluded.source='configured_seed'
                              AND catalog_discovery_queue.state IN ('DONE','DEAD'))""",
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
                affected += max(0, int(cursor.rowcount or 0))
    finally:
        conn.close()
    return affected
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
    """Persist discovered Deloox URLs in short, independently committed chunks.

    Deloox discovery shares SQLite with search and hydration workers. Holding one
    write transaction for an entire category page can block offer persistence
    and queue claims. Small chunks release the writer lock between groups while
    preserving the same idempotent URL/queue upserts.
    """
    if not product_urls:
        return 0
    now = time.time()
    conn = db()
    count = 0
    items = list(product_urls.items())
    transaction_batch_size = 25
    store_url_sql = """INSERT INTO store_urls(
                           store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                           slug=excluded.slug,
                           lastmod=CASE
                               WHEN excluded.lastmod != '' THEN excluded.lastmod
                               ELSE store_urls.lastmod
                           END,
                           active=1
                       WHERE store_urls.slug IS NOT excluded.slug
                          OR (excluded.lastmod != ''
                              AND store_urls.lastmod IS NOT excluded.lastmod)
                          OR store_urls.active != 1"""
    hydration_sql = """INSERT INTO hydration_queue(
                           store,url,state,attempts,available_at,first_seen_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                           state=CASE
                               WHEN hydration_queue.state='DONE' THEN 'DONE'
                               WHEN hydration_queue.state='PROCESSING'
                                    AND hydration_queue.leased_until > ?
                               THEN 'PROCESSING'
                               WHEN EXISTS (
                                   SELECT 1 FROM store_products p
                                    WHERE p.store='deloox'
                                      AND p.url=hydration_queue.url
                                      AND p.fetch_status='OK'
                               ) THEN 'DONE'
                               ELSE 'PENDING'
                           END,
                           available_at=CASE
                               WHEN hydration_queue.state IN ('ERROR','DEAD')
                                AND NOT EXISTS (
                                   SELECT 1 FROM store_products p
                                    WHERE p.store='deloox'
                                      AND p.url=hydration_queue.url
                                      AND p.fetch_status='OK'
                                ) THEN excluded.available_at
                               ELSE MIN(hydration_queue.available_at, excluded.available_at)
                           END"""
    try:
        for chunk_start in range(0, len(items), transaction_batch_size):
            chunk = items[chunk_start:chunk_start + transaction_batch_size]
            with conn:
                for url, lastmod in chunk:
                    conn.execute(
                        store_url_sql,
                        ('deloox', url, url_slug(url), lastmod or '', now),
                    )
                    conn.execute(
                        hydration_sql,
                        ('deloox', url, 'PENDING', 0, now, now, now),
                    )
                    count += 1
    finally:
        conn.close()
    return count

def _discover_deloox_search_catalog(deadline=None):
    """Import the Deloox scraper's proven generic search discovery into catalog.

    The production Deloox scraper already knows how to traverse the public
    search surface and its numeric pagination. Catalog discovery must reuse
    that capability for retailer-wide terms instead of maintaining a second,
    divergent pagination implementation.

    This is background catalog coverage only: no user query, product name,
    brand, SKU, variant, or individual product URL is supplied.
    """
    try:
        module = importlib.import_module('scrapers.deloox.scraper')
        discover = getattr(module, '_discover', None)
        if not callable(discover):
            return {'queries': [], 'products': 0, 'errors': ['deloox_scraper_discover_unavailable']}
    except Exception as exc:
        return {'queries': [], 'products': 0, 'errors': [f'import:{type(exc).__name__}:{exc}']}

    started = time.time()
    product_urls = {}
    errors = []
    reports = []
    session = requests.Session()
    try:
        for query in DELOOX_GENERIC_CATALOG_QUERIES:
            if deadline is not None and time.time() >= float(deadline):
                break
            try:
                urls = discover(session, query, deadline=deadline) or []
                added = 0
                for raw in urls:
                    if not raw:
                        continue
                    url = str(raw).split('#', 1)[0]
                    if not _deloox_queue_allowed(url):
                        continue
                    if url not in product_urls:
                        product_urls[url] = ''
                        added += 1
                reports.append({
                    'query': query,
                    'returned': len(urls),
                    'added': added,
                })
            except Exception as exc:
                error = f'{query}:{type(exc).__name__}:{exc}'
                errors.append(error)
                reports.append({'query': query, 'returned': 0, 'added': 0, 'error': error})
    finally:
        session.close()

    if product_urls:
        _deloox_persist_products(product_urls)

    return {
        'queries': reports,
        'products': len(product_urls),
        'product_urls': product_urls,
        'errors': errors[:8],
        'elapsed_sec': round(time.time() - started, 3),
    }


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

    # Reuse the Deloox scraper's already-proven public search pagination for
    # generic catalog coverage. This runs before the durable graph crawl so
    # every URL returned by that discovery path is handed directly to the
    # persistent catalog/hydration layer.
    search_deadline = min(
        time.time() + 45.0,
        float(deadline) if deadline is not None else time.time() + 45.0,
    )
    search_catalog = _discover_deloox_search_catalog(search_deadline)
    for url in search_catalog.get('product_urls', {}):
        product_urls[url] = ''
    errors.extend(search_catalog.get('errors') or [])

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
        page_products = set()

        def admit(raw, label=''):
            product = _html_product_url('deloox', raw, base)
            if product:
                product_urls[product] = ''
                page_products.add(product)
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

        # Deloox search results are paginated by a numeric `page` parameter
        # that is not always exposed as a normal <a rel="next"> link. Follow
        # the next page while the current page actually yielded product URLs.
        # This is generic catalog discovery: no product, brand, or query is
        # hardcoded here.
        sp = urllib.parse.urlparse(requested)
        if (
            page_products
            and re.search(r'/(?:chercher|search)(?:\.html)?$', sp.path or '', re.I)
            and re.search(r'(?:^|&)(?:q|query)=', sp.query, re.I)
        ):
            params = urllib.parse.parse_qsl(sp.query, keep_blank_values=True)
            current = 1
            for key, value in params:
                if key.lower() == 'page' and value.isdigit():
                    current = int(value)
            if current < DELOOX_SEARCH_MAX_PAGES:
                params = [(k, v) for k, v in params if k.lower() != 'page']
                params.append(('page', str(current + 1)))
                listings.append((
                    urllib.parse.urlunparse(sp._replace(
                        query=urllib.parse.urlencode(params, doseq=True),
                        fragment='',
                    )),
                    depth,
                    requested,
                ))

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
        # Persist only products discovered on this page. Persisting the
        # cumulative catalog-wide product_urls mapping here rewrites every
        # previously discovered URL on every page (quadratic DB work), which
        # can hold SQLite's write lock long enough to stall discovery and
        # hydration. The search-discovery phase persists its own results.
        if page_products:
            _deloox_persist_products({url: '' for url in page_products})
        return True

    max_run_seconds = 120.0
    if deadline is not None:
        max_run_seconds = max(1.0, float(deadline) - time.time())
    run_deadline = time.time() + min(max_run_seconds, 120.0)

    while time.time() < run_deadline:
        batch = _deloox_queue_claim(limit=HTML_WORKERS, lease_seconds=180)
        if not batch:
            break

        with ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=min(HTML_WORKERS, len(batch))) as pool:
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
    started = time.time()
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
        # Do not let ThreadPoolExecutor's context manager wait indefinitely
        # for unfinished network tasks when the discovery deadline is reached.
        pool = ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=min(HTML_WORKERS, len(batch)))
        futures = {pool.submit(_fetch_html_page, store, u): (u, d, source)
                   for u, d, source in batch}
        try:
            remaining = None if deadline is None else max(0.01, deadline - time.time())
            for f in as_completed(futures, timeout=remaining):
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
                    host_patterns = _allowed_store_hosts(store)
                    candidates = set()
                    for match in re.finditer(
                        r'''https?://[^"'\s<>\\]+|/(?:[A-Za-z0-9._~-]+/){1,}[^"'\s<>\\]+''',
                        raw_html,
                        re.I,
                    ):
                        raw = match.group(0)
                        absolute = urllib.parse.urljoin(page_base, raw).split('#', 1)[0]
                        parsed = urllib.parse.urlparse(absolute)
                        if not parsed.hostname or parsed.hostname.lower().rstrip('.') not in host_patterns:
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
        except FuturesTimeoutError:
            pending = [meta[0] for future, meta in futures.items() if not future.done()]
            errors.append(f'discovery_deadline_reached; pending_pages={len(pending)}')
        finally:
            _set_sync_state(
                store, 'DISCOVERY_RUNNING',
                started_at=(deadline - DISCOVERY_HARD_TIMEOUT if deadline is not None else started),
                discovered_count=len(product_urls), fetched_count=successes,
                error=(
                    f'phase=html_fallback;last_progress_at={time.time():.3f};'
                    f'visited={len(visited)};queued={len(queue)};'
                    f'products_found={len(product_urls)};successes={successes};'
                    f'errors={len(errors)};deadline={deadline}'
                ),
            )
            for future in futures:
                if not future.done():
                    future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

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
    # This endpoint is an interactive diagnostic, not a full crawl. Keep each
    # network request and the overall trace bounded so clients receive JSON
    # instead of waiting for the production discovery timeout (up to 300 s).
    trace_budget_seconds = 12.0
    trace_request_timeout = min(float(HTTP_TIMEOUT), 4.0)
    successes = 0

    while queue and len(visited) < max_pages and (time.time() - started) < trace_budget_seconds:
        _priority, _sequence, requested, depth, source = heapq.heappop(queue)
        if requested in visited:
            continue
        visited.add(requested)
        try:
            _requested, final, data, error = _fetch_html_page(
                store, requested, timeout=trace_request_timeout
            )
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
        # Parse only navigation elements. The retailer's category page can be ~1 MB;
        # parsing the entire DOM and extracting all text made this diagnostic exceed
        # its time budget even when only one page was visited.
        soup = BeautifulSoup(data, 'html.parser', parse_only=SoupStrainer(['a', 'link']))
        # The page-hit signal is derived from the requested/final URL and link labels;
        # avoid a full-document text extraction in this read-only diagnostic.
        page_hit = has_tokens(requested) or has_tokens(final)
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
        'parameters': {
            'max_pages': max_pages, 'max_depth': max_depth, 'max_events': max_events,
            'max_elapsed_seconds': trace_budget_seconds,
            'request_timeout_seconds': trace_request_timeout,
        },
        'timed_out': bool(queue and (time.time() - started) >= trace_budget_seconds),
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
    def _persist_seed_progress(detail):
        _set_sync_state(
            store, 'DISCOVERY_RUNNING', started_at=started_at,
            discovered_count=0, fetched_count=0, error=detail,
        )

    roots,robots_diagnostics=_seed_sitemaps(store, progress_callback=_persist_seed_progress)
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
        # Bound the wait itself, not only the outer loop. A context-managed
        # executor waits for every worker on exit and can defeat the deadline.
        pool = ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=min(SYNC_WORKERS, len(batch)))
        futures = {pool.submit(_fetch_sitemap, store, sm): (sm, depth)
                   for sm, depth in batch}
        try:
            remaining = max(0.01, sitemap_deadline - time.time())
            for f in as_completed(futures, timeout=remaining):
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
        except FuturesTimeoutError:
            sitemap_errors.append(
                f'sitemap_batch_deadline_reached; pending={sum(1 for f in futures if not f.done())}'
            )
        finally:
            _set_sync_state(
                store, 'DISCOVERY_RUNNING', started_at=started_at,
                discovered_count=len(product_urls), fetched_count=sitemap_successes,
                error=(
                    f'phase=sitemap;last_progress_at={time.time():.3f};'
                    f'visited={len(visited)};queued={len(queue)};'
                    f'products_found={len(product_urls)};successes={sitemap_successes};'
                    f'xml_entries={sitemap_url_entries};errors={len(sitemap_errors)}'
                ),
            )
            for future in futures:
                if not future.done():
                    future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

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
            store in ('sabina', 'parfumzentrum', 'easycosmetic')
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
    # Avoid BeautifulSoup's CSS selector engine here. Some retailer pages
    # contain very large/deep HTML trees; soupsieve.select() can spend a long
    # time recursively matching the selector, tying up a hydration worker.
    # A direct tag scan has identical matching semantics for this JSON-LD type.
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
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
    # Product identity and price fallback need only the visible H1 and JSON-LD
    # scripts. Retaining the full retailer DOM made CSS selection over very
    # large pages consume CPU for tens of seconds and delayed hydration/status.
    soup = BeautifulSoup(
        data,
        'html.parser',
        parse_only=SoupStrainer(['h1', 'script']),
    )
    h1 = soup.find('h1')
    h1text = h1.get_text(' ', strip=True) if h1 else ''
    products = _jsonld(soup)

    # Retailer pages can contain several Product JSON-LD objects (variants,
    # recommendations, related products). Prefer the object that matches the
    # visible page title instead of blindly taking the first JSON-LD Product.
    def _name_key(value):
        value = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode('ascii')
        return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()

    p = {}
    if products and h1text:
        title_key = _name_key(h1text)
        title_tokens = set(title_key.split())
        best_score = -1.0
        for candidate in products:
            candidate_name = _name_key(candidate.get('name'))
            if not candidate_name:
                continue
            candidate_tokens = set(candidate_name.split())
            overlap = len(title_tokens & candidate_tokens) / max(1, len(title_tokens | candidate_tokens))
            containment = 1.0 if title_key in candidate_name or candidate_name in title_key else 0.0
            score = containment + overlap
            if score > best_score:
                best_score, p = score, candidate
    elif products:
        p = products[0]

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
        # Some adapters expose _extract_product with different historical
        # signatures: (url, query), (session, url, query), or keyword-only
        # query/session arguments. Bind by parameter name so a valid adapter
        # is not permanently dead-lettered because its calling convention
        # differs from ParfumZentrum's.
        parser = getattr(module, '_extract_product', None)
        if not callable(parser):
            return None
        parser_url = original_url or final_url
        parser_query = re.sub(r'\bz\d+\s*$', '', url_slug(parser_url), flags=re.I).strip()
        parameters = inspect.signature(parser).parameters
        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})
        try:
            args = []
            kwargs = {}
            for parameter in parameters.values():
                if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                name = parameter.name.lower()
                if name in {'session', 'sess', 'client', 'http', 'http_session'}:
                    value = session
                elif name in {'url', 'product_url', 'page_url', 'final_url'}:
                    value = parser_url
                elif name in {'query', 'search_query', 'product_query', 'q'}:
                    value = parser_query
                elif parameter.default is not inspect.Parameter.empty:
                    continue
                else:
                    # Unknown required parameter: do not guess its meaning.
                    raise TypeError(f'unsupported _extract_product parameter: {parameter.name}')
                if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                    kwargs[parameter.name] = value
                else:
                    args.append(value)
            parsed = parser(*args, **kwargs)
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

    source = parsed.get('source') or {}
    attributes = parsed.get('attributes') or {}
    offer = parsed.get('offer') or {}

    def attribute_value(key):
        value = attributes.get(key)
        if isinstance(value, dict):
            return value.get('value')
        return value

    price = parsed.get('price_num')
    if price is None:
        price = offer.get('price')

    availability = (
        parsed.get('availability')
        or offer.get('availability')
        or 'unknown'
    )
    available = parsed.get('available')
    if available is None:
        if availability == 'in_stock':
            available = True
        elif availability == 'out_of_stock':
            available = False

    return {
        'store': STORE_LABELS[store],
        'store_key': store,
        'url': parsed.get('url') or source.get('url') or original_url or final_url,
        'name': parsed.get('name') or parsed.get('title') or source.get('name') or '',
        'brand': parsed.get('brand') or source.get('brand') or '',
        'image': parsed.get('image') or source.get('image'),
        'sku': parsed.get('sku') or identity_value('sku') or '',
        'gtin': parsed.get('gtin') or identity_value('gtin') or '',
        'mpn': parsed.get('mpn') or identity_value('mpn') or '',
        'size_ml': parsed.get('size_ml') if parsed.get('size_ml') is not None else attribute_value('size_ml'),
        'concentration': parsed.get('concentration') or attribute_value('concentration'),
        'gender': parsed.get('gender') or attribute_value('gender'),
        'price_num': price,
        'price': price,
        'currency': parsed.get('currency') or offer.get('currency') or 'EUR',
        'availability': availability,
        'available': available,
        'variants': parsed.get('variants') if store == 'sabina' and isinstance(parsed.get('variants'), list) else [],
        'fetched_at': time.time(),
    }


def refresh_url(store, url):
    try:
        if store == 'easycosmetic':
            # Enforce the German storefront on the requested URL as well as
            # the final redirect URL. Checking only the final URL can otherwise
            # persist a legacy .be (or other regional) URL after it redirects
            # to .de, leaving a non-canonical URL in the durable catalog.
            requested = urllib.parse.urlparse(str(url or ''))
            requested_host = (requested.hostname or '').lower().rstrip('.')
            if (
                requested.scheme not in ('http', 'https')
                or requested_host not in {'easycosmetic.de', 'www.easycosmetic.de'}
            ):
                raise RuntimeError(
                    f'non_german_easycosmetic_url;requested={url}'
                )

        # Keep retailer fetches bounded; Requests' (connect, read) timeout
        # is still not a hard wall-clock deadline if a server dribbles bytes.
        # Deloox response headers can stall, so run this fetch in the existing
        # batch worker with a short socket timeout and let the batch deadline
        # release the scheduler if the peer never responds.
        if store == 'easycosmetic':
            store_timeout = max(25, REFRESH_TIMEOUT)
        elif store == 'deloox':
            store_timeout = (3.0, 3.0)
        else:
            store_timeout = REFRESH_TIMEOUT
        status, final, data = http_get(url, timeout=store_timeout)
        if status >= 400:
            raise RuntimeError(f'HTTP {status}')

        if store == 'easycosmetic':
            # Never hydrate or publish a German catalog entry from a response
            # that redirected to a different regional storefront.
            final_host = (urllib.parse.urlparse(str(final or '')).hostname or '').lower().rstrip('.')
            if final_host not in {'easycosmetic.de', 'www.easycosmetic.de'}:
                raise RuntimeError(
                    f'non_german_easycosmetic_redirect;final={final}'
                )

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

        parser_error = None
        if parser_available:
            try:
                item = _secondary_store_parser(store, final, url, html_data=data)
                secondary_ok = bool(item and item.get('name'))
            except Exception as exc:
                # A retailer adapter bug must not discard an otherwise valid
                # product page. Keep the exception in diagnostics and attempt
                # the structured-data fallback before recording a queue error.
                parser_error = f'{type(exc).__name__}:{exc}'
                item = None
            if not item or not item.get('name'):
                fallback_item = parse_product(store, final, data)
                if fallback_item and fallback_item.get('name'):
                    item = fallback_item
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
                f';parser_error={parser_error!r}'
                f';h1={h1_text!r}'
            )
            print(f'CATALOG PRODUCT PARSER DIAG: store={store} url={url} {detail}', flush=True)
            raise RuntimeError(detail)

        conn = db()
        try:
            # A successful targeted refresh must also make this URL part of the
            # persistent searchable catalog. Previously only store_products
            # was written, while search_local() and the FTS triggers require an
            # active store_urls row. This left valid refreshed offers invisible.
            now = time.time()
            with conn:
                conn.execute(
                    '''INSERT INTO store_urls(
                           store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                           slug=excluded.slug,
                           discovered_at=excluded.discovered_at,
                           active=1''',
                    (store, url, url_slug(url), None, now),
                )
                conn.execute(
                    '''INSERT INTO hydration_queue(
                           store,url,state,attempts,available_at,first_seen_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                           state=CASE
                               WHEN hydration_queue.state='DONE' THEN 'DONE'
                               WHEN hydration_queue.state='PROCESSING'
                                    AND hydration_queue.leased_until > ?
                               THEN 'PROCESSING'
                               ELSE hydration_queue.state
                           END''',
                    (store, url, "PENDING", 0, now, now, now),
                )
                if store == 'sabina' and item.get('variants'):
                    # Validate the complete extracted set before replacing the
                    # stored set. A malformed/non-priced extraction must never
                    # erase previously known good variant offers.
                    valid_variants = []
                    for variant in item['variants']:
                        try:
                            variant_size = float(variant.get('size_ml'))
                            variant_price = float(variant.get('price_num'))
                        except (TypeError, ValueError):
                            continue
                        if variant_size > 0 and variant_price > 0:
                            valid_variants.append((variant, variant_size, variant_price))
                    if valid_variants:
                        conn.execute('DELETE FROM store_product_variants WHERE store=? AND url=?', (store, url))
                        for variant, variant_size, variant_price in valid_variants:
                            # Persist the commercial combination identity, not
                            # merely size + SKU: Sabina can repeat a parent SKU
                            # across sizes, and distinct combinations may share
                            # both size and SKU. The scraper preserves the real
                            # combination selector in the variant URL fragment.
                            raw_variant_url = str(variant.get('url') or '').strip()
                            parsed_variant_url = urllib.parse.urlparse(raw_variant_url)
                            variant_selector = (parsed_variant_url.fragment or '').strip().lstrip('/')
                            variant_query = urllib.parse.parse_qs(parsed_variant_url.query)
                            selector_values = []
                            for selector_name in ('id_product_attribute', 'id_product_attribute_value', 'variant', 'variant_id', 'combination_id'):
                                selector_values.extend(str(value).strip() for value in variant_query.get(selector_name, []) if str(value).strip())
                            if selector_values:
                                identity_token = 'selector:' + '|'.join(selector_values)
                            elif variant_selector:
                                identity_token = 'fragment:' + variant_selector
                            elif variant.get('gtin'):
                                identity_token = 'gtin:' + str(variant.get('gtin')).strip()
                            elif variant.get('mpn'):
                                identity_token = 'mpn:' + str(variant.get('mpn')).strip()
                            elif variant.get('sku'):
                                identity_token = 'sku:' + str(variant.get('sku')).strip()
                            else:
                                identity_token = 'price:' + format(variant_price, '.4f')
                            variant_key = f"{variant_size:g}ml:{identity_token}"
                            # Variant identity must not inherit identifiers that
                            # describe the parent product (notably GTIN/MPN).
                            # A parent-level GTIN is not proof that every size
                            # has that same GTIN.
                            variant_name = variant.get('name') or item.get('name')
                            if variant_name and not variant.get('name'):
                                # Make each offer name describe its own volume.
                                variant_name = re.sub(
                                    r"\s+\d+(?:[.,]\d+)?\s*(?:ml|cl|l)\s*$",
                                    "",
                                    str(variant_name),
                                    flags=re.I,
                                ).strip()
                                variant_name = f"{variant_name} {variant_size:g} ML".strip()
                            variant_gtin = variant.get('gtin')
                            variant_mpn = variant.get('mpn')
                            if len(valid_variants) == 1:
                                variant_gtin = variant_gtin or item.get('gtin')
                                variant_mpn = variant_mpn or item.get('mpn')
                            conn.execute(
                                '''INSERT INTO store_product_variants(
                                    store,url,variant_key,name,brand,image,sku,gtin,mpn,size_ml,
                                    concentration,gender,price,currency,availability,fetched_at,variant_url)
                                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                   ON CONFLICT(store,url,variant_key) DO UPDATE SET
                                    name=excluded.name,brand=excluded.brand,image=excluded.image,
                                    sku=excluded.sku,gtin=excluded.gtin,mpn=excluded.mpn,
                                    size_ml=excluded.size_ml,concentration=excluded.concentration,
                                    gender=excluded.gender,price=excluded.price,currency=excluded.currency,
                                    availability=excluded.availability,fetched_at=excluded.fetched_at,
                                    variant_url=excluded.variant_url''',
                                (store,url,variant_key,variant_name,item.get('brand'),item.get('image'),
                                 variant.get('sku') or item.get('sku'),variant_gtin,variant_mpn,
                                 variant_size,item.get('concentration'),item.get('gender'),variant_price,
                                 variant.get('currency') or item.get('currency') or 'EUR',
                                 variant.get('availability') or item.get('availability'),now,
                                 _sabina_variant_url(variant.get('url'), url, variant_size) if store == 'sabina' else (_store_allowed_variant_url(store, variant.get('url'), url) or url)),
                            )
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
        finally:
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
        with _LAST_REFRESH_ERRORS_LOCK:
            _LAST_REFRESH_ERRORS.pop((store, url), None)
        return item
    except Exception as exc:
        error_detail = 'ERROR:' + type(exc).__name__ + (f': {exc}' if str(exc) else '')
        with _LAST_REFRESH_ERRORS_LOCK:
            _LAST_REFRESH_ERRORS[(store, url)] = error_detail

        conn = db()
        try:
            # Do not replace a previously successful offer with a transient
            # timeout/parser/SQLite error. Search and price comparison must
            # continue using the last known-good price until a newer fetch
            # succeeds. Only create an ERROR row when no valid offer exists.
            existing = conn.execute(
                "SELECT fetch_status FROM store_products WHERE store=? AND url=?",
                (store, url),
            ).fetchone()
            has_good_offer = bool(existing and existing['fetch_status'] == 'OK')
            if not has_good_offer:
                conn.execute(
                    '''INSERT INTO store_products(store,url,fetched_at,fetch_status)
                       VALUES(?,?,?,?)
                       ON CONFLICT(store,url) DO UPDATE SET
                       fetched_at=excluded.fetched_at,fetch_status=excluded.fetch_status''',
                    (store, url, time.time(), error_detail),
                )
            # A ParfumZentrum placeholder price is a known terminal outcome.
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
        finally:
            conn.close()

        # Preserve an existing valid offer in both SQLite and the in-memory
        # index after transient failures. A known invalid placeholder remains
        # terminal and is removed from search.
        if placeholder_offer or not has_good_offer:
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


# Refresh stale retailer prices independently of the short interactive-search budget.
_STALE_PRICE_REPAIR_LOCK = threading.Lock()
_STALE_PRICE_REPAIR_IN_FLIGHT = set()

def _schedule_stale_price_repairs(rows, max_jobs=12):
    # Prioritize stale offers surfaced by the current search. Otherwise a large
    # backlog of unrelated, older catalog rows can consume every repair slot,
    # leaving the exact Hawas candidates searched by the user pending indefinitely.
    # Fill remaining slots from a database-wide stale scan so background repair
    # still progresses beyond the current query.
    cutoff = time.time() - 24 * 60 * 60
    jobs = []
    seen = set()

    def add_stale(store_value, url_value, fetched_at=None):
        store = str(store_value or '').strip().lower()
        url = str(url_value or '').strip()
        if store not in STORES or not url or (store, url) in seen:
            return
        try:
            fetched = float(fetched_at or 0)
        except (TypeError, ValueError):
            fetched = 0.0
        if fetched > 0 and fetched > cutoff:
            return
        seen.add((store, url))
        jobs.append((store, url))

    # Search-relevant candidates go first, but only if their persisted prices
    # are actually stale. This makes repeated searches repair the products they
    # are trying to show rather than unrelated rows at the head of the backlog.
    for row in rows or []:
        if isinstance(row, dict):
            add_stale(
                row.get('store_key') or row.get('store'),
                row.get('product_url') or row.get('url'),
                row.get('fetched_at'),
            )

    try:
        conn = db()
        try:
            stale_rows = conn.execute(
                """SELECT store, url, fetched_at
                   FROM store_products
                   WHERE fetched_at IS NULL OR fetched_at <= ?
                   ORDER BY COALESCE(fetched_at, 0) ASC
                   LIMIT ?""",
                (cutoff, max_jobs * 8),
            ).fetchall()
        finally:
            conn.close()
        for row in stale_rows:
            add_stale(row['store'], row['url'], row['fetched_at'])
    except Exception as exc:
        print(f"CATALOG STALE PRICE SCAN ERROR {type(exc).__name__}:{exc}", flush=True)

    selected = jobs[:max_jobs]
    for store, url in selected:
        key = (store, url)
        with _STALE_PRICE_REPAIR_LOCK:
            if key in _STALE_PRICE_REPAIR_IN_FLIGHT:
                continue
            _STALE_PRICE_REPAIR_IN_FLIGHT.add(key)

        def _repair(target_store=store, target_url=url, target_key=key):
            try:
                result = refresh_url(target_store, target_url)
                print(
                    f"CATALOG STALE PRICE REFRESH {'OK' if result else 'FAILED'} "
                    f"store={target_store} url={target_url} "
                    f"price={result.get('price_num') if result else None}",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"CATALOG STALE PRICE REFRESH ERROR store={target_store} "
                    f"url={target_url} error={type(exc).__name__}:{exc}",
                    flush=True,
                )
            finally:
                with _STALE_PRICE_REPAIR_LOCK:
                    _STALE_PRICE_REPAIR_IN_FLIGHT.discard(target_key)

        threading.Thread(target=_repair, name='catalog-stale-price-refresh', daemon=True).start()


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
        _schedule_stale_price_repairs(rows)
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
           AND (
               f.store != 'easycosmetic'
               OR lower(u.url) LIKE 'https://www.easycosmetic.de/%'
               OR lower(u.url) LIKE 'http://www.easycosmetic.de/%'
               OR lower(u.url) LIKE 'https://easycosmetic.de/%'
               OR lower(u.url) LIKE 'http://easycosmetic.de/%'
               OR lower(u.url) = 'https://www.easycosmetic.de'
               OR lower(u.url) = 'http://www.easycosmetic.de'
               OR lower(u.url) = 'https://easycosmetic.de'
               OR lower(u.url) = 'http://easycosmetic.de'
           )
         ORDER BY CASE WHEN p.name IS NOT NULL THEN 0 ELSE 1 END, rank
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
        # Search the original query (first token set) across every store before
        # spending the shared deadline on expanded query variants. The previous
        # store-first loop could exhaust the budget on earlier retailers before
        # reaching the requested retailer's exact query.
        for ts in token_sets:
            if interrupted():
                break
            for store in STORES:
                if interrupted():
                    break
                per_store_counts = {}
                seen_product_keys = set()
                # Sabina bottle sizes live in store_product_variants, not in the
                # URL-level FTS document. Keep size tokens for the variant-level
                # filter below, but don't require them to exist in the page title.
                sabina_size_tokens = set()
                fts_tokens = ts
                if store == 'sabina' and any(token in ts for token in {'ml', 'milliliter', 'milliliters', 'millilitre', 'millilitres'}):
                    sabina_size_tokens = {
                        token for token in ts
                        if token.isdigit() or token in {'ml', 'milliliter', 'milliliters', 'millilitre', 'millilitres'}
                    }
                    fts_tokens = tuple(token for token in ts if token not in sabina_size_tokens)
                fts_query = _fts_query_for_tokens(fts_tokens)
                if not fts_query:
                    # A size alone is not enough to identify a product page;
                    # do not turn this into a broad catalog scan.
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
                    required_base_tokens = tuple(token for token in ts if token not in sabina_size_tokens) if store == 'sabina' else ts
                    if not all(token in normalized_tokens for token in required_base_tokens):
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
                        variant_rows = []
                        if store == 'sabina':
                            try:
                                variant_rows = conn.execute(
                                    "SELECT * FROM store_product_variants WHERE store=? AND url=? ORDER BY size_ml",
                                    (store, url),
                                ).fetchall()
                            except sqlite3.OperationalError:
                                variant_rows = []
                        if variant_rows:
                            for vr in variant_rows:
                                if not all(token in set(norm(' '.join((str(r['slug'] or ''), str(r['product_name'] or ''), str(r['product_brand'] or ''), f"{vr['size_ml'] or ''} ml"))).split()) for token in ts):
                                    continue
                                rows.append({
                                    'url': (_sabina_variant_url(vr['variant_url'] if 'variant_url' in vr.keys() and vr['variant_url'] else url, url, vr['size_ml']) if store == 'sabina' else (vr['variant_url'] if 'variant_url' in vr.keys() and vr['variant_url'] else url)),
                                    'product_url': url, 'slug': r['slug'] or '', 'lastmod': r['lastmod'] or '',
                                    'name': vr['name'] or r['product_name'] or '', 'brand': vr['brand'] or r['product_brand'] or '',
                                    'image': vr['image'] or r['product_image'] or '', 'sku': vr['sku'] or r['product_sku'] or '',
                                    'gtin': vr['gtin'] or r['product_gtin'] or '', 'mpn': vr['mpn'] or r['product_mpn'] or '',
                                    'size_ml': vr['size_ml'], 'concentration': vr['concentration'] or r['product_concentration'] or '',
                                    'gender': vr['gender'] or r['product_gender'] or '', 'price': vr['price'],
                                    'currency': vr['currency'] or 'EUR', 'availability': vr['availability'] or r['product_availability'] or '',
                                    'fetched_at': vr['fetched_at'], 'fetch_status': 'OK', 'price_num': vr['price'],
                                    'store': STORE_LABELS[store], 'store_key': store, 'variant_key': vr['variant_key'],
                                })
                            continue
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

        # Expanded query terms can match the same catalog URL repeatedly.
        # Deduplicate only after collecting all terms, so a later size-specific
        # term can still contribute a distinct retailer variant. Keep separate
        # bottle sizes, and otherwise use the actual offer URL as identity.
        unique_rows = []
        seen_local_offer_keys = set()
        for item in rows:
            store_key = str(item.get('store_key') or item.get('store') or '').strip().lower()
            parent_url = str(item.get('product_url') or item.get('url') or '').strip().lower()
            offer_url = str(item.get('url') or item.get('product_url') or '').strip().lower()
            raw_size = item.get('size_ml')
            try:
                size_value = float(str(raw_size).strip().replace(',', '.')) if raw_size not in (None, '') else None
            except (TypeError, ValueError):
                size_value = None
            # Prefer the catalog's stable variant key, then a real URL selector.
            # Size is a fallback discriminator only: it must not collapse two
            # same-size commercial combinations with different selector URLs.
            variant_key = str(item.get('variant_key') or '').strip().lower()
            selector = ''
            if '#' in offer_url:
                candidate_fragment = offer_url.split('#', 1)[1].strip('/')
                if re.search(
                    r'\d+.*(?:size|tama|ml|variant|attribute|combination)|'
                    r'(?:size|tama|ml|variant|attribute|combination).*\d+',
                    candidate_fragment, re.I,
                ):
                    selector = 'fragment:' + candidate_fragment
            if not selector:
                selector_match = re.search(
                    r'[?&](?:variant|variant_id|id_product_attribute|combination_id)=([^&#]+)',
                    offer_url, re.I,
                )
                if selector_match:
                    selector = 'query:' + selector_match.group(1)
            if variant_key:
                offer_variant = ('variant_key', variant_key)
            elif selector:
                offer_variant = ('selector', selector, round(size_value, 3) if size_value and size_value > 0 else '')
            elif size_value is not None and size_value > 0:
                offer_variant = ('size_ml', round(size_value, 3))
            else:
                offer_variant = ('url', offer_url)
            local_key = (store_key, parent_url, offer_variant)
            if local_key in seen_local_offer_keys:
                continue
            seen_local_offer_keys.add(local_key)

            # A stale persisted price is not a valid current comparison offer.
            # Keep the product discoverable, but never display its old price as
            # current while background hydration catches up. A fresh successful
            # refresh restores the price through the normal persistence path.
            try:
                fetched_at = float(item.get('fetched_at') or 0)
            except (TypeError, ValueError):
                fetched_at = 0.0
            if item.get('price_num') not in (None, '') and (
                fetched_at <= 0 or time.time() - fetched_at > 24 * 60 * 60
            ):
                item = dict(item)
                item['_needs_refresh'] = True
                # Keep the last known price available while hydration is queued.
                # The public API can expose freshness separately; hiding price
                # here makes the entire search fail whenever the short refresh
                # budget cannot finish a retailer HTTP request.

            unique_rows.append(item)

        print(
            f"CATALOG SEARCH DIAG total={time.monotonic()-_diag_t0:.3f}s "
            f"rows={len(rows)} unique_rows={len(unique_rows)}", flush=True
        )
        return unique_rows
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
                   AND (
                       u.store != 'easycosmetic'
                       OR lower(u.url) LIKE 'https://www.easycosmetic.de/%'
                       OR lower(u.url) LIKE 'http://www.easycosmetic.de/%'
                       OR lower(u.url) LIKE 'https://easycosmetic.de/%'
                       OR lower(u.url) LIKE 'http://easycosmetic.de/%'
                       OR lower(u.url) = 'https://www.easycosmetic.de'
                       OR lower(u.url) = 'http://www.easycosmetic.de'
                       OR lower(u.url) = 'https://easycosmetic.de'
                       OR lower(u.url) = 'http://easycosmetic.de'
                   )
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
    pool = ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=min(REFRESH_WORKERS, len(jobs)))
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


def prioritize_hydration_candidates(rows, priority=0):
    """Give query-selected, unhydrated products first claim after foreground search.

    This is deliberately best-effort and bounded: never wait behind a long
    SQLite writer on a user-search path. Failed priority hints do not affect
    search correctness; durable hydration continues with the normal FIFO queue.
    """
    updates = []
    try:
        value = max(0, int(priority))
    except (TypeError, ValueError):
        value = 0
    for row in rows or ():
        if not isinstance(row, dict) or not row.get('_needs_refresh'):
            continue
        store = str(row.get('store_key') or row.get('store') or '').strip().lower()
        url = str(row.get('url') or row.get('product_url') or '').strip()
        if store in STORES and url:
            updates.append((value, store, url))
    if not updates:
        return 0

    conn = sqlite3.connect(str(DB_PATH), timeout=0.15)
    conn.execute('PRAGMA busy_timeout=150')
    priority_sql = """UPDATE hydration_queue
                         SET priority=MIN(priority,?)
                       WHERE store=? AND url=?
                         AND state IN ('PENDING','ERROR')
                         AND EXISTS (
                             SELECT 1 FROM store_urls u
                              WHERE u.store=hydration_queue.store
                                AND u.url=hydration_queue.url
                                AND u.active=1
                         )"""
    try:
        conn.execute('BEGIN IMMEDIATE')
        before = conn.total_changes
        conn.executemany(priority_sql, updates)
        conn.commit()
        return conn.total_changes - before
    except sqlite3.OperationalError as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(
            'CATALOG HYDRATION PRIORITY HINT SKIPPED '
            f'error={type(exc).__name__}:{exc}',
            flush=True,
        )
        return 0
    finally:
        conn.close()


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


def _ensure_hydration_queue(max_rows=1200, batch_size=100, max_seconds=8.0):
    """Perform a bounded, resumable queue backfill without monopolizing SQLite.

    This bootstrap helper is intentionally budgeted per process start. It scans
    a limited keyset page range, commits small batches and returns; the durable
    claim/retry loop keeps processing existing queue rows normally. Re-running
    on the next app start continues to be safe and idempotent.
    """
    max_rows = max(1, int(max_rows))
    batch_size = max(1, min(int(batch_size), 200))
    deadline = time.monotonic() + max(0.5, float(max_seconds))
    scanned_after = None
    inserted = 0
    invalidated = 0
    scanned = 0
    complete = False

    conn = db()
    try:
        while scanned < max_rows and time.monotonic() < deadline:
            limit = min(batch_size, max_rows - scanned)
            if scanned_after is None:
                rows = conn.execute(
                    """SELECT store,url FROM store_urls
                        WHERE active=1 ORDER BY store,url LIMIT ?""",
                    (limit,),
                ).fetchall()
            else:
                last_store, last_url = scanned_after
                rows = conn.execute(
                    """SELECT store,url FROM store_urls
                        WHERE active=1
                          AND (store > ? OR (store = ? AND url > ?))
                        ORDER BY store,url LIMIT ?""",
                    (last_store, last_store, last_url, limit),
                ).fetchall()
            if not rows:
                complete = True
                break

            scanned_after = (rows[-1]['store'], rows[-1]['url'])
            scanned += len(rows)
            valid, invalid = [], []
            for row in rows:
                pair = (row['store'], row['url'])
                (valid if _looks_product(row['url'], row['store']) else invalid).append(pair)

            now = time.time()
            with conn:
                if invalid:
                    conn.executemany(
                        "DELETE FROM hydration_queue WHERE store=? AND url=?",
                        invalid,
                    )
                    conn.executemany(
                        "UPDATE store_urls SET active=0 WHERE store=? AND url=?",
                        invalid,
                    )
                    invalidated += len(invalid)
                if valid:
                    conn.executemany(
                        """INSERT OR IGNORE INTO hydration_queue(
                               store,url,state,attempts,available_at,first_seen_at)
                           SELECT ?,?,CASE WHEN EXISTS(
                               SELECT 1 FROM store_products p
                                WHERE p.store=? AND p.url=? AND p.fetch_status='OK'
                           ) THEN 'DONE' ELSE 'PENDING' END,0,?,?""",
                        [(store, url, store, url, now, now) for store, url in valid],
                    )
                    inserted += len(valid)

        print(
            'HYDRATION QUEUE BACKFILL '
            f'scanned={scanned} cursor={scanned_after!r} complete={complete} '
            f'inserted_candidates={inserted} invalidated={invalidated} '
            f'max_rows={max_rows} batch_size={batch_size} elapsed_sec={max(0.0, max_seconds - max(0.0, deadline-time.monotonic())):.2f}',
            flush=True,
        )
        return {'scanned': scanned, 'inserted': inserted, 'invalidated': invalidated, 'complete': complete}
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
    except sqlite3.OperationalError as exc:
        print(
            f'CATALOG HYDRATION STAGE ERROR: stage=recover_stale_tasks '
            f'error={type(exc).__name__}: {exc}',
            flush=True,
        )
        traceback.print_exc()
        raise
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
    # Claiming is a hot-path operation shared with discovery and coverage.
    # Do not let this worker sit behind SQLite's global 45s busy timeout.
    conn = sqlite3.connect(str(DB_PATH), timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=2000')
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
                     q.priority ASC,
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
    except sqlite3.OperationalError as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        print(
            f'CATALOG HYDRATION STAGE ERROR: stage=claim_hydration_task '
            f'error={type(exc).__name__}: {exc}',
            flush=True,
        )
        traceback.print_exc()
        raise
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

        # Only known terminal outcomes are dead-lettered. Network timeouts,
        # parser failures and temporary SQLite contention remain retryable after
        # the initial attempt budget, at the capped 24-hour backoff interval.
        terminal_http = http_status in (404, 410)
        terminal_placeholder = 'invalid_placeholder_price' in str(error)
        next_state = 'DEAD' if terminal_http or terminal_placeholder else 'ERROR'
        if next_state == 'ERROR' and attempts >= HYDRATION_MAX_ATTEMPTS:
            delay = float(HYDRATION_BACKOFF_SECONDS[-1])
            next_time = now + delay + delay * HYDRATION_RETRY_JITTER * (0.5 + (time.time() % 0.5))
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
        with _LAST_REFRESH_ERRORS_LOCK:
            detail = _LAST_REFRESH_ERRORS.get((task['store'], task['url']))
        if not detail:
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
    except sqlite3.OperationalError as exc:
        print(
            f'CATALOG HYDRATION STAGE ERROR: stage=hydrate_task '
            f'store={task.get("store")} url={task.get("url")} '
            f'error={type(exc).__name__}: {exc}',
            flush=True,
        )
        traceback.print_exc()
        try:
            _queue_mark_error(task, f'{type(exc).__name__}: {exc}')
        except Exception:
            traceback.print_exc()
        return False
    except Exception as exc:
        _queue_mark_error(task, f'{type(exc).__name__}: {exc}')
        return False


def hydrate_catalog_batch(max_urls=2, workers=HYDRATION_WORKERS, deadline=None, stores=None):
    """Process one bounded durable hydration batch without waiting on hung parsers.

    The lease-token checks remain the authority for queue transitions. When a
    future exceeds the batch deadline we stop waiting for it and let its lease
    expire; a late worker cannot mark a reclaimed task DONE because its token
    no longer matches. Running threads cannot be forcibly killed in Python, so
    parser/network work must still use finite bounds wherever possible.
    """
    # Backfill is deliberately not part of this hot loop.
    recover_stale_tasks()

    limit = max(1, int(max_urls))
    worker_count = max(1, min(int(workers), HYDRATION_WORKERS, limit))
    tasks = []
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

    pool = ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=min(worker_count, len(tasks)))
    futures = {pool.submit(_hydrate_one_task, task): task for task in tasks}
    pending = set(futures)
    fetched = 0
    errors = 0
    timed_out = 0
    cancelled = False
    try:
        while pending:
            if _foreground_search_running():
                cancelled = True
                for future in pending:
                    future.cancel()
                break

            if deadline is not None and time.monotonic() >= float(deadline):
                timed_out += len(pending)
                cancelled = True
                for future in pending:
                    # Only tasks that have not started can be cancelled. For
                    # running tasks, leave the lease to expire so a later
                    # claim gets a fresh token and stale work cannot mark DONE.
                    future.cancel()
                break

            done = {future for future in pending if future.done()}
            if not done:
                time.sleep(0.05)
                continue

            for future in done:
                pending.discard(future)
                try:
                    result = future.result()
                    if result is True:
                        fetched += 1
                    elif result is False:
                        errors += 1
                except sqlite3.OperationalError as exc:
                    print(
                        'CATALOG HYDRATION STAGE ERROR: stage=hydration_future '
                        f'error={type(exc).__name__}: {exc}',
                        flush=True,
                    )
                    traceback.print_exc()
                    errors += 1
                except Exception as exc:
                    print(
                        'CATALOG HYDRATION FUTURE ERROR: '
                        f'{type(exc).__name__}: {exc}',
                        flush=True,
                    )
                    traceback.print_exc()
                    errors += 1

        if timed_out:
            print(
                'CATALOG HYDRATION BATCH DEADLINE '
                f'pending={timed_out} lease_seconds={HYDRATION_LEASE_SECONDS:g}',
                flush=True,
            )
        return {
            'selected': len(tasks),
            'fetched': fetched,
            'errors': errors,
            'timed_out': timed_out,
        }
    finally:
        # Crucial: wait=False prevents an old/hung parser from blocking the
        # scheduler loop. Running tasks may finish later, but all queue
        # transitions validate their original lease token.
        pool.shutdown(wait=not cancelled, cancel_futures=cancelled)


def _recover_stale_discovery_states():
    """Close persisted RUNNING states left behind by a killed/restarted process.

    A discovery run is bounded by DISCOVERY_HARD_TIMEOUT. A RUNNING row older
    than that budget plus a small grace period cannot represent a live run in
    this process and otherwise remains misleading until that retailer's next
    round-robin turn. This only updates sync_state metadata; catalog URLs and
    product offers are never touched.
    """
    now = time.time()
    stale_before = now - max(60.0, float(DISCOVERY_HARD_TIMEOUT) + 60.0)
    conn = db()
    recovered = []
    try:
        rows = conn.execute(
            "SELECT store, started_at FROM sync_state WHERE status='DISCOVERY_RUNNING'"
        ).fetchall()
        with conn:
            for row in rows:
                store = str(row['store'] or '')
                started_at = row['started_at']
                try:
                    started_epoch = float(started_at) if started_at is not None else None
                except (TypeError, ValueError):
                    started_epoch = None
                is_stale = started_epoch is None or started_epoch < stale_before
                if not store or not is_stale:
                    continue
                age = round(now - started_epoch, 1) if started_epoch is not None else None
                detail = (
                    'discovery_interrupted_by_process_restart;'
                    f'stale_age_sec={age if age is not None else "unknown"}'
                )
                updated = conn.execute(
                    """UPDATE sync_state
                       SET status='DISCOVERY_ERROR', finished_at=?, error=?
                       WHERE store=? AND status='DISCOVERY_RUNNING'
                         AND started_at IS ?""",
                    (now, detail, store, started_at),
                ).rowcount
                if updated:
                    recovered.append(store)
    finally:
        conn.close()
    if recovered:
        print(
            'CATALOG DISCOVERY STALE STATES RECOVERED '
            f'stores={",".join(sorted(recovered))}',
            flush=True,
        )
    return recovered


def _set_catalog_discovery_os_thread_name(thread, name):
    """Keep Python and Linux /proc thread names in sync on Python 3.12.

    The separate family-coverage process reads /proc/<pid>/task/<tid>/comm;
    changing Thread.name alone does not reliably rename a running OS thread on
    Python versions before 3.14. PR_SET_NAME is thread-local and Linux truncates
    the name to 15 bytes, matching the coverage worker's detection contract.
    """
    thread.name = name
    try:
        encoded = str(name).encode("utf-8")[:15]
        result = ctypes.CDLL(None, use_errno=True).prctl(
            15, ctypes.c_char_p(encoded), 0, 0, 0
        )
        if result != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_NAME) failed")
    except Exception as exc:
        print(
            "CATALOG DISCOVERY OS THREAD NAME ERROR "
            f"name={name} error={type(exc).__name__}:{exc}",
            flush=True,
        )


def catalog_discovery_loop(stop_event, interval_seconds=300.0):
    """Incrementally advance discovery for every retailer in the background.

    Only one retailer is crawled per interval, in round-robin order. The loop
    yields while foreground searches are active or in their idle grace period.
    This does not add network work to the user-facing search request; the
    existing local index remains the only search-time catalog source.
    """
    pause = max(60.0, float(interval_seconds))
    stores = tuple(STORES.keys())
    if not stores:
        print('CATALOG DISCOVERY STOP: no configured stores', flush=True)
        return
    next_index = 0
    non_deloox_stores = tuple(store for store in stores if store != 'deloox')
    next_non_deloox_index = 0
    non_deloox_since_deloox = 0
    # After a process restart, repair Deloox's persisted discovery state on the
    # first eligible background turn instead of making it wait behind two
    # unrelated retailers. Foreground searches still take precedence.
    prioritize_deloox_on_start = 'deloox' in stores
    try:
        _recover_stale_discovery_states()
    except Exception as exc:
        print(
            'CATALOG DISCOVERY STALE STATE RECOVERY ERROR '
            f'{type(exc).__name__}: {exc}',
            flush=True,
        )
    print(
        f'CATALOG DISCOVERY START stores={len(stores)} interval={pause:g}s',
        flush=True,
    )
    # The family-coverage worker checks this process-visible name to avoid
    # overlapping writes. Mark the thread idle between bounded crawls; leaving
    # the discovery name set for the lifetime of this loop starves coverage.
    discovery_thread = threading.current_thread()
    _set_catalog_discovery_os_thread_name(discovery_thread, 'sh-catalog-idle')
    while stop_event is None or not stop_event.is_set():
        # Avoid starting a new crawl while a user search is active or another
        # search is likely to arrive immediately after the previous one.
        if _foreground_search_running() or _foreground_search_idle_grace_active():
            if stop_event is not None:
                stop_event.wait(0.5)
            else:
                time.sleep(0.5)
            continue

        # Deloox has the largest outstanding frontier. Visit it after every two
        # other retailers instead of once per full seven-store round-robin.
        # Other retailers retain their own round-robin progress, and foreground
        # searches still take precedence over every background crawl.
        if prioritize_deloox_on_start:
            store = 'deloox'
            prioritize_deloox_on_start = False
            non_deloox_since_deloox = 0
        elif non_deloox_stores and 'deloox' in stores and non_deloox_since_deloox >= 2:
            store = 'deloox'
            non_deloox_since_deloox = 0
        elif non_deloox_stores:
            store = non_deloox_stores[next_non_deloox_index % len(non_deloox_stores)]
            next_non_deloox_index = (next_non_deloox_index + 1) % len(non_deloox_stores)
            non_deloox_since_deloox += 1
        else:
            store = stores[next_index % len(stores)]
            next_index = (next_index + 1) % len(stores)
        started = time.time()
        _set_catalog_discovery_os_thread_name(discovery_thread, 'sh-catalog-discovery')
        try:
            result = discover_store(store)
            if not isinstance(result, dict):
                result = {'status': 'unknown', 'count': '?'}
            print(
                'CATALOG DISCOVERY BATCH '
                f'store={store} status={result.get("status", "unknown")} '
                f'count={result.get("count", "?")}',
                flush=True,
            )
        except Exception as exc:
            error_detail = f'{type(exc).__name__}: {exc}'
            print(
                f'CATALOG DISCOVERY ERROR store={store}: {error_detail}',
                flush=True,
            )
            # discover_store marks DISCOVERY_RUNNING before network work. If an
            # unexpected exception escapes it, persist a terminal state so the
            # public status cannot remain RUNNING forever with a stale deadline.
            try:
                _set_sync_state(
                    store,
                    'DISCOVERY_ERROR',
                    started_at=started,
                    finished_at=time.time(),
                    error=error_detail[:1000],
                )
            except Exception as state_exc:
                print(
                    f'CATALOG DISCOVERY STATE ERROR store={store}: '
                    f'{type(state_exc).__name__}: {state_exc}',
                    flush=True,
                )

        # Only expose the active-writer name while discover_store is running.
        # The coverage worker can safely resume during the interval sleep.
        _set_catalog_discovery_os_thread_name(discovery_thread, 'sh-catalog-idle')

        # Wait between stores. The event wait allows clean shutdown and keeps
        # discovery from immediately starting another potentially expensive
        # retailer crawl.
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
    """Keep the store x canonical-product coverage matrix complete and current.

    Do not use a total-row-count shortcut here: coverage is a matrix keyed by
    (store, product_id), so the same row count can hide missing combinations
    when products or configured stores change. Existing tasks remain untouched
    unless their canonical identity/query changes; changed tasks are reopened.
    """
    if not products or not STORES:
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
    if not rows:
        return
    statement = """INSERT INTO catalog_coverage(
               store,product_id,canonical_name,query,state,next_run_at)
           VALUES(?,?,?,?, 'PENDING', ?)
           ON CONFLICT(store,product_id) DO UPDATE SET
               state=CASE
                   WHEN catalog_coverage.canonical_name != excluded.canonical_name
                     OR catalog_coverage.query != excluded.query
                   THEN 'PENDING' ELSE catalog_coverage.state END,
               next_run_at=CASE
                   WHEN catalog_coverage.canonical_name != excluded.canonical_name
                     OR catalog_coverage.query != excluded.query
                   THEN excluded.next_run_at ELSE catalog_coverage.next_run_at END,
               found_urls=CASE
                   WHEN catalog_coverage.canonical_name != excluded.canonical_name
                     OR catalog_coverage.query != excluded.query
                   THEN 0 ELSE catalog_coverage.found_urls END,
               last_error=CASE
                   WHEN catalog_coverage.canonical_name != excluded.canonical_name
                     OR catalog_coverage.query != excluded.query
                   THEN NULL ELSE catalog_coverage.last_error END,
               last_finished_at=CASE
                   WHEN catalog_coverage.canonical_name != excluded.canonical_name
                     OR catalog_coverage.query != excluded.query
                   THEN NULL ELSE catalog_coverage.last_finished_at END,
               canonical_name=excluded.canonical_name,
               query=excluded.query"""
    # Keep each write transaction small. Coverage seeding runs alongside catalog
    # hydration, discovery and searches, so one large executemany can monopolize
    # SQLite's single-writer lock.
    chunk_size = 100
    for offset in range(0, len(rows), chunk_size):
        chunk = rows[offset:offset + chunk_size]
        for attempt in range(5):
            try:
                conn.executemany(statement, chunk)
                conn.commit()
                break
            except sqlite3.OperationalError as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                if attempt >= 4:
                    raise
                time.sleep(0.25 * (2 ** attempt))


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
    with ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=worker_count) as pool:
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
        except sqlite3.OperationalError as exc:
            print(
                f'CATALOG HYDRATION STAGE ERROR: stage=hydration_loop '
                f'error={type(exc).__name__}: {exc}',
                flush=True,
            )
            traceback.print_exc()
            if stop_event is not None:
                stop_event.wait(5.0)
            else:
                time.sleep(5.0)
        except Exception as exc:
            print(
                f'CATALOG HYDRATION ERROR: {type(exc).__name__}: {exc}',
                flush=True,
            )
            traceback.print_exc()
            if stop_event is not None:
                stop_event.wait(5.0)
            else:
                time.sleep(5.0)


def hydration_status():
    """Bounded read-only hydration status, grouped in one pass over active URLs."""
    # Do not call db(): it runs schema initialization and waits up to 45 seconds
    # on SQLite locks. Diagnostics must never queue behind catalog writers.
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=2000')
    conn.execute('PRAGMA query_only=ON')
    out = {
        store: {
            'total': 0, 'pending': 0, 'processing': 0, 'done': 0,
            'error': 0, 'dead': 0, 'last_finished_at': None,
        }
        for store in STORES
    }
    try:
        rows = conn.execute(
            """SELECT q.store,
                      COUNT(*) AS total,
                      SUM(CASE WHEN q.state='PENDING' THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN q.state='PROCESSING' THEN 1 ELSE 0 END) AS processing,
                      SUM(CASE WHEN q.state='DONE' THEN 1 ELSE 0 END) AS done,
                      SUM(CASE WHEN q.state='ERROR' THEN 1 ELSE 0 END) AS error,
                      SUM(CASE WHEN q.state='DEAD' THEN 1 ELSE 0 END) AS dead,
                      MAX(q.last_finished_at) AS last_finished_at
               FROM hydration_queue q
               GROUP BY q.store"""
        ).fetchall()
        for row in rows:
            store = row['store']
            if store not in out:
                continue
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
    with ThreadPoolExecutor(initializer=_set_catalog_pool_worker_os_name, max_workers=min(SYNC_WORKERS, len(STORES))) as pool:
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
    """Return inexpensive store status without catalog-wide join scans.

    The public status endpoint is hit by health checks and diagnostics while
    the hydration and discovery workers write to the same SQLite database.
    Keep this path read-only and bound its wait for SQLite's single writer.
    Exact active URL counts remain available from store_urls; fetched and
    pending figures use lightweight aggregates with a short busy timeout.
    """
    # Read-only connection avoids waiting for writer/schema initialization;
    # diagnostics should degrade quickly rather than stall production probes.
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=2000')
    conn.execute('PRAGMA query_only=ON')
    now = time.time()
    out = {}
    try:
        sync_rows = {
            row['store']: row
            for row in conn.execute('SELECT store,status,finished_at,error FROM sync_state')
        }
        url_counts = {
            row['store']: int(row['count'] or 0)
            for row in conn.execute(
                'SELECT store,COUNT(*) AS count FROM store_urls WHERE active=1 GROUP BY store'
            )
        }
        product_counts = {
            row['store']: int(row['count'] or 0)
            for row in conn.execute(
                '''SELECT store,COUNT(*) AS count FROM store_products
                   WHERE fetch_status='OK' GROUP BY store'''
            )
        }
        # Restrict the queue aggregate to active store URLs without running one
        # LEFT JOIN/count pair per retailer; the query is grouped once.
        # Use the durable queue for outstanding hydration counts. A
        # catalog-wide LEFT JOIN between URLs and products is expensive under
        # concurrent discovery/hydration writes and is unnecessary for status.
        pending_counts = {
            row['store']: int(row['count'] or 0)
            for row in conn.execute(
                """SELECT q.store,COUNT(*) AS count
                     FROM hydration_queue q
                     JOIN store_urls u
                       ON u.store=q.store AND u.url=q.url
                    WHERE u.active=1 AND q.state != 'DONE'
                    GROUP BY q.store"""
            )
        }
        for store in STORES:
            sync = sync_rows.get(store)
            count = url_counts.get(store, 0)
            fetched = product_counts.get(store, 0)
            derived_status = (
                sync['status'] if sync else
                ('READY' if fetched else 'INDEXED' if count else 'NOT_SYNCED')
            )
            out[store] = {
                'status': derived_status,
                'indexed_urls': count,
                'fetched_products': fetched,
                'pending_hydration': pending_counts.get(store, 0),
                'hydration_ratio': round((fetched / count), 4) if count else 0.0,
                'finished_at': sync['finished_at'] if sync else None,
                'age_sec': (now - sync['finished_at']) if sync and sync['finished_at'] else None,
                'error': sync['error'] if sync else None,
            }
    finally:
        conn.close()
    return out


if __name__ == '__main__':
    print(json.dumps(sync_all(), indent=2, ensure_ascii=False))

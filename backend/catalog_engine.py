# ScentHunter V5 - catalog-first store index
# Search never calls retailer search endpoints. Retailer discovery is a background/indexing job.
import json, re, sqlite3, threading, time, unicodedata, urllib.parse, urllib.request, urllib.robotparser, importlib, gzip, xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    # Deloox exposes multiple localized hosts; the indexer starts from the primary site.
    'deloox': 'https://www.deloox.com',
}

STORE_LABELS = {k: ''.join(x.capitalize() for x in k.replace('-', ' ').split()) for k in STORES}
STORE_LABELS.update({'parfumcity':'ParfumCity','parfumzentrum':'ParfumZentrum','perfumemarket':'PerfumeMarket','easycosmetic':'Easycosmetic','bplatz':'Bplatz','deloox':'Deloox','sabina':'Sabina','orioudh':'Orioudh'})

USER_AGENT = 'ScentHunterBot/5.0 (+price-comparison; catalog indexing)'
HTTP_TIMEOUT = 10
MAX_SITEMAPS_PER_STORE = 500
MAX_URLS_PER_SITEMAP = 50000
MAX_SITEMAP_DEPTH = 8
SITEMAP_TIMEOUT = 10

# Store-level discovery configuration only: public storefront hosts.
DISCOVERY_BASES = {
    'deloox': (
        'https://www.deloox.com',
        'https://www.deloox.be',
        'https://www.deloox.nl',
        'https://www.deloox.lu',
        'https://www.deloox.es',
    ),
}
SYNC_WORKERS = 8
REFRESH_WORKERS = 8
REFRESH_TIMEOUT = 8

# Generic product URL signals. These are intentionally not product-specific.
NON_PRODUCT_PATH = re.compile(r'/(?:search|suche|chercher|suchen|buscar|category|categorie|categoria|brand|brands|marca|marque|sitemap|login|account|cart|checkout|blog|news|tag|tags)(?:/|$)', re.I)
PRODUCT_EXT = re.compile(r'\.(?:html?|php)$', re.I)


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


def http_get(url, timeout=HTTP_TIMEOUT):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), r.read()


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('''CREATE TABLE IF NOT EXISTS store_urls(
        store TEXT NOT NULL, url TEXT NOT NULL, slug TEXT NOT NULL,
        lastmod TEXT, discovered_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(store,url))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_store_urls_slug ON store_urls(store,slug)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS store_products(
        store TEXT NOT NULL, url TEXT NOT NULL, name TEXT, brand TEXT, image TEXT,
        sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL, concentration TEXT, gender TEXT,
        price REAL, currency TEXT, availability TEXT, fetched_at REAL, fetch_status TEXT,
        PRIMARY KEY(store,url))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_store_products_store_name ON store_products(store,name)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS sync_state(
        store TEXT PRIMARY KEY, status TEXT, started_at REAL, finished_at REAL,
        discovered_count INTEGER DEFAULT 0, fetched_count INTEGER DEFAULT 0, error TEXT)''')
    conn.commit()
    return conn


def _discovery_bases(store):
    return tuple(dict.fromkeys(DISCOVERY_BASES.get(store, (STORES[store],))))


def _seed_sitemaps(store):
    """Discover public sitemap roots from robots.txt plus standard names."""
    roots = []
    for base in _discovery_bases(store):
        base = base.rstrip('/')
        roots.extend((
            base + '/sitemap.xml',
            base + '/sitemap_index.xml',
            base + '/sitemap-index.xml',
            base + '/sitemaps.xml',
        ))
        try:
            status, final, data = http_get(base + '/robots.txt', timeout=5)
            if status < 400:
                text = data.decode('utf-8', 'ignore')
                roots.extend(re.findall(
                    r'(?im)^\s*sitemap\s*:\s*(https?://[^\s#]+)', text
                ))
        except Exception:
            continue
    return list(dict.fromkeys(roots))


def _decode_sitemap(data, url=''):
    """Decode XML sitemap payloads, including gzip and mislabeled gzip."""
    if not data:
        return b''
    raw = bytes(data)
    if raw[:2] == b'\x1f\x8b' or str(url).lower().split('?', 1)[0].endswith('.gz'):
        try:
            return gzip.decompress(raw)
        except Exception:
            pass
    return raw


def _xml_local(tag):
    return str(tag or '').rsplit('}', 1)[-1].lower()


def _parse_xml_urls(data, url=''):
    """Parse sitemapindex/urlset independent of XML namespaces."""
    raw = _decode_sitemap(data, url)
    if not raw:
        return []

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
                    child_kind = _xml_local(child.tag)
                    if child_kind == 'loc':
                        loc = (child.text or '').strip()
                    elif child_kind == 'lastmod':
                        lastmod = (child.text or '').strip()
                if loc:
                    out.append(('sitemap', loc, lastmod))
            return out

        if kind == 'urlset':
            out = []
            for node in list(root):
                if _xml_local(node.tag) != 'url':
                    continue
                loc = ''
                lastmod = ''
                for child in list(node):
                    child_kind = _xml_local(child.tag)
                    if child_kind == 'loc':
                        loc = (child.text or '').strip()
                    elif child_kind == 'lastmod':
                        lastmod = (child.text or '').strip()
                if loc:
                    out.append(('url', loc, lastmod))
            return out
    except Exception:
        pass

    try:
        soup = BeautifulSoup(raw, 'xml')
        if soup.find('sitemapindex') or soup.find('sitemap'):
            out = []
            for node in soup.find_all('sitemap'):
                loc = node.find('loc')
                if loc and loc.get_text(strip=True):
                    last = node.find('lastmod')
                    out.append(('sitemap', loc.get_text(strip=True),
                                last.get_text(strip=True) if last else ''))
            if out:
                return out
        out = []
        for node in soup.find_all('url'):
            loc = node.find('loc')
            if loc and loc.get_text(strip=True):
                last = node.find('lastmod')
                out.append(('url', loc.get_text(strip=True),
                            last.get_text(strip=True) if last else ''))
        return out
    except Exception:
        return []


def _looks_product(url):
    """Broad URL admission; product-vs-category is decided after page fetch."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https') or p.fragment:
        return False
    if NON_PRODUCT_PATH.search(p.path):
        return False
    path = urllib.parse.unquote(p.path).rstrip('/')
    if not path or path == '/':
        return False
    return len(url_slug(url).split()) >= 2


def _fetch_sitemap(store, sm):
    try:
        status, final, data = http_get(sm, timeout=SITEMAP_TIMEOUT)
        if status >= 400:
            return sm, final, [], f'HTTP {status}'
        entries = _parse_xml_urls(data, final or sm)
        if not entries:
            return sm, final, [], 'empty_or_unparseable_xml'
        return sm, final, entries, None
    except Exception as exc:
        return sm, sm, [], f'{type(exc).__name__}: {exc}'


def discover_store(store):
    """Build a persistent URL catalog from the retailer's public sitemap tree."""
    roots = _seed_sitemaps(store)
    queue = [(url, 0) for url in roots]
    queued = set(roots)
    visited = set()
    product_urls = {}
    sitemap_errors = []
    sitemap_successes = 0
    sitemap_url_entries = 0

    while queue and len(visited) < MAX_SITEMAPS_PER_STORE:
        batch = []
        while queue and len(batch) < SYNC_WORKERS * 4:
            sm, depth = queue.pop(0)
            if sm in visited:
                continue
            visited.add(sm)
            batch.append((sm, depth))
        if not batch:
            continue

        with ThreadPoolExecutor(max_workers=min(SYNC_WORKERS, len(batch))) as pool:
            futures = {pool.submit(_fetch_sitemap, store, sm): (sm, depth)
                       for sm, depth in batch}
            for future in as_completed(futures):
                sm, depth = futures[future]
                try:
                    _source, final, entries, error = future.result()
                except Exception as exc:
                    final, entries = sm, []
                    error = f'{type(exc).__name__}: {exc}'

                if error:
                    sitemap_errors.append(f'{sm}: {error}')
                    continue

                sitemap_successes += 1
                sitemap_url_entries += len(entries)

                for kind, url, lastmod in entries:
                    if not url:
                        continue
                    absolute = urllib.parse.urljoin(final or sm, url)
                    if kind == 'sitemap':
                        if depth + 1 <= MAX_SITEMAP_DEPTH and absolute not in queued:
                            queued.add(absolute)
                            queue.append((absolute, depth + 1))
                    elif _looks_product(absolute):
                        product_urls[absolute] = lastmod or ''

                if len(product_urls) >= MAX_URLS_PER_SITEMAP * 2:
                    queue.clear()
                    break

    now = time.time()
    conn = db()

    if product_urls:
        with conn:
            conn.execute('UPDATE store_urls SET active=0 WHERE store=?', (store,))
            for url, lastmod in product_urls.items():
                conn.execute(
                    """INSERT INTO store_urls
                       (store,url,slug,lastmod,discovered_at,active)
                       VALUES(?,?,?,?,?,1)
                       ON CONFLICT(store,url) DO UPDATE SET
                       slug=excluded.slug,lastmod=excluded.lastmod,
                       discovered_at=excluded.discovered_at,active=1""", 
                    (store, url, url_slug(url), lastmod, now)
                )
            conn.execute(
                """INSERT INTO sync_state
                   (store,status,started_at,finished_at,discovered_count,
                    fetched_count,error)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(store) DO UPDATE SET
                   status=excluded.status,finished_at=excluded.finished_at,
                   discovered_count=excluded.discovered_count,error=excluded.error""", 
                (store, 'DISCOVERY_OK', now, now, len(product_urls), 0, None)
            )
    else:
        detail = (
            f'no_product_urls; sitemap_successes={sitemap_successes}; '
            f'visited={len(visited)}; xml_entries={sitemap_url_entries}; '
            f'errors={len(sitemap_errors)}'
        )
        conn.execute(
            """INSERT INTO sync_state
               (store,status,started_at,finished_at,discovered_count,
                fetched_count,error)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(store) DO UPDATE SET
               status=excluded.status,finished_at=excluded.finished_at,
               discovered_count=excluded.discovered_count,error=excluded.error""", 
            (store, 'DISCOVERY_EMPTY', now, now, 0, 0, detail)
        )
        conn.commit()

    conn.close()
    return {
        'count': len(product_urls),
        'status': 'DISCOVERY_OK' if product_urls else 'DISCOVERY_EMPTY',
        'visited_sitemaps': len(visited),
        'sitemap_successes': sitemap_successes,
        'xml_entries': sitemap_url_entries,
        'errors': sitemap_errors[:20],
    }

def _jsonld(soup):
    products=[]
    for script in soup.select('script[type="application/ld+json"]'):
        raw=script.string or script.get_text()
        try: data=json.loads(raw)
        except Exception: continue
        stack=data if isinstance(data,list) else [data]
        while stack:
            x=stack.pop()
            if isinstance(x,list): stack.extend(x); continue
            if not isinstance(x,dict): continue
            typ=x.get('@type'); types=typ if isinstance(typ,list) else [typ]
            if any(str(t).lower()=='product' for t in types): products.append(x)
            for v in x.values():
                if isinstance(v,(dict,list)): stack.append(v)
    return products


def _num(v):
    if v is None or v=='': return None
    try: return float(v)
    except Exception: pass
    s=re.sub(r'[^0-9,.\-]','',str(v))
    if ',' in s and '.' in s:
        if s.rfind(',')>s.rfind('.'): s=s.replace('.','').replace(',','.')
        else: s=s.replace(',','')
    elif ',' in s: s=s.replace(',','.')
    try:return float(s)
    except:return None


def _first_offer(p):
    offers=p.get('offers') if isinstance(p,dict) else None
    if isinstance(offers,dict): return offers
    if isinstance(offers,list):
        for o in offers:
            if isinstance(o,dict) and (_num(o.get('price')) is not None or o.get('availability')): return o
    return {}


def parse_product(store,url,data):
    soup=BeautifulSoup(data,'html.parser')
    h1=soup.find('h1')
    h1text=h1.get_text(' ',strip=True) if h1 else ''
    products=_jsonld(soup)
    p=products[0] if products else {}
    name=str(p.get('name') or h1text or '').strip()
    if not name: return None
    brand=p.get('brand')
    if isinstance(brand,dict): brand=brand.get('name')
    offer=_first_offer(p)
    price=_num(offer.get('price'))
    currency=str(offer.get('priceCurrency') or 'EUR')
    availability=str(offer.get('availability') or '').lower()
    if 'instock' in availability or 'limitedavailability' in availability or 'onlineonly' in availability: availability='in_stock'
    elif any(x in availability for x in ('outofstock','soldout','discontinued')): availability='out_of_stock'
    elif 'preorder' in availability: availability='preorder'
    else: availability='unknown'
    image=p.get('image')
    if isinstance(image,list): image=image[0] if image else None
    if isinstance(image,dict): image=image.get('url') or image.get('contentUrl')
    return {
        'store':STORE_LABELS[store],'store_key':store,'url':url,'name':name,'brand':str(brand or '').strip(),
        'image':image,'sku':str(p.get('sku') or '').strip(),'gtin':str(p.get('gtin13') or p.get('gtin12') or p.get('gtin14') or p.get('gtin') or '').strip(),
        'mpn':str(p.get('mpn') or '').strip(),'price_num':price,'price':price,'currency':currency,
        'availability':availability,'available': True if availability=='in_stock' else False if availability=='out_of_stock' else None,
        'fetched_at':time.time()
    }


def refresh_url(store,url):
    try:
        status,final,data=http_get(url,timeout=REFRESH_TIMEOUT)
        if status>=400: raise RuntimeError(f'HTTP {status}')
        item=parse_product(store,final,data)
        if not item:
            # Store-specific parser is a SECONDARY product-page parser only.
            # Discovery remains catalog-first and never calls the retailer search endpoint.
            try:
                module=importlib.import_module(f'scrapers.{store}.scraper')
                parser=getattr(module,'extract_product_page',None)
                if callable(parser):
                    import requests
                    session=requests.Session()
                    parsed=parser(session, final, url_slug(final))
                    session.close()
                    if isinstance(parsed,dict):
                        item={
                            'store':STORE_LABELS[store], 'store_key':store, 'url':parsed.get('url') or final,
                            'name':parsed.get('name') or parsed.get('title') or '',
                            'brand':parsed.get('brand') or '', 'image':parsed.get('image') or (parsed.get('source') or {}).get('image'),
                            'sku':parsed.get('sku') or ((parsed.get('identity') or {}).get('sku') or {}).get('value') if isinstance((parsed.get('identity') or {}).get('sku'),dict) else parsed.get('sku'),
                            'gtin':parsed.get('gtin') or ((parsed.get('identity') or {}).get('gtin') or {}).get('value') if isinstance((parsed.get('identity') or {}).get('gtin'),dict) else parsed.get('gtin'),
                            'mpn':parsed.get('mpn') or ((parsed.get('identity') or {}).get('mpn') or {}).get('value') if isinstance((parsed.get('identity') or {}).get('mpn'),dict) else parsed.get('mpn'),
                            'price_num':parsed.get('price_num') if parsed.get('price_num') is not None else (parsed.get('offer') or {}).get('price'),
                            'price':parsed.get('price_num') if parsed.get('price_num') is not None else (parsed.get('offer') or {}).get('price'),
                            'currency':parsed.get('currency') or (parsed.get('offer') or {}).get('currency') or 'EUR',
                            'availability':parsed.get('availability') or (parsed.get('offer') or {}).get('availability') or 'unknown',
                            'available':parsed.get('available'), 'fetched_at':time.time()
                        }
                if not item or not item.get('name'):
                    item=None
            except Exception:
                item=None
        if not item: raise RuntimeError('product_parser_not_found')
        conn=db()
        conn.execute('''INSERT INTO store_products(store,url,name,brand,image,sku,gtin,mpn,size_ml,concentration,gender,price,currency,availability,fetched_at,fetch_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(store,url) DO UPDATE SET name=excluded.name,brand=excluded.brand,image=excluded.image,sku=excluded.sku,gtin=excluded.gtin,mpn=excluded.mpn,price=excluded.price,currency=excluded.currency,availability=excluded.availability,fetched_at=excluded.fetched_at,fetch_status=excluded.fetch_status''', (store,url,item['name'],item['brand'],item['image'],item['sku'],item['gtin'],item['mpn'],None,None,None,item['price_num'],item['currency'],item['availability'],item['fetched_at'],'OK'))
        conn.commit();conn.close();return item
    except Exception as e:
        conn=db();conn.execute('INSERT INTO store_products(store,url,fetched_at,fetch_status) VALUES(?,?,?,?) ON CONFLICT(store,url) DO UPDATE SET fetched_at=excluded.fetched_at,fetch_status=excluded.fetch_status',(store,url,time.time(),'ERROR:'+type(e).__name__));conn.commit();conn.close();return None


def search_local(query, per_store=12):
    ts=tokens(query)
    if not ts:return []
    conn=db(); rows=[]
    for store in STORES:
        # URL/slug discovery is local. No network call occurs here.
        candidates=conn.execute('SELECT url,slug,lastmod FROM store_urls WHERE store=? AND active=1', (store,)).fetchall()
        scored=[]
        for r in candidates:
            s=r['slug']; score=sum(1 for t in ts if t in s)
            if score==len(ts): score+=10
            if score>=len(ts): scored.append((score,r['url']))
        scored.sort(key=lambda x:(-x[0],x[1]))
        for _,url in scored[:per_store]:
            row=conn.execute('SELECT * FROM store_products WHERE store=? AND url=?',(store,url)).fetchone()
            if row:
                item=dict(row); item['price_num']=item.get('price'); item['store']=STORE_LABELS[store]; item['store_key']=store; rows.append(item)
            else:
                rows.append({'store':STORE_LABELS[store],'store_key':store,'url':url,'name':url_slug(url),'_needs_refresh':True})
    conn.close();return rows


def refresh_candidates(rows):
    jobs=[(r['store_key'],r['url']) for r in rows if r.get('_needs_refresh')]
    out=[]
    if not jobs:return out
    with ThreadPoolExecutor(max_workers=min(REFRESH_WORKERS,len(jobs))) as pool:
        futures=[pool.submit(refresh_url,s,u) for s,u in jobs]
        for f in as_completed(futures):
            try:
                x=f.result()
                if x:out.append(x)
            except Exception:pass
    return out


def sync_all():
    results = {}
    with ThreadPoolExecutor(max_workers=min(SYNC_WORKERS, len(STORES))) as pool:
        futures = {pool.submit(discover_store, store): store for store in STORES}
        for future, store in futures.items():
            try:
                results[store] = future.result()
            except Exception as exc:
                results[store] = {
                    'count': 0,
                    'status': 'DISCOVERY_ERROR',
                    'error': f'{type(exc).__name__}: {exc}',
                }
                conn = db()
                now = time.time()
                conn.execute(
                    """INSERT INTO sync_state
                       (store,status,started_at,finished_at,discovered_count,
                        fetched_count,error)
                       VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(store) DO UPDATE SET
                       status=excluded.status,finished_at=excluded.finished_at,
                       error=excluded.error""", 
                    (store, 'DISCOVERY_ERROR', now, now, 0, 0,
                     f'{type(exc).__name__}: {exc}')
                )
                conn.commit()
                conn.close()
    return results

def store_status():
    conn=db(); now=time.time();out={}
    for store in STORES:
        r=conn.execute('SELECT * FROM sync_state WHERE store=?',(store,)).fetchone()
        count=conn.execute('SELECT COUNT(*) c FROM store_urls WHERE store=? AND active=1',(store,)).fetchone()['c']
        fetched=conn.execute('SELECT COUNT(*) c FROM store_products WHERE store=? AND fetch_status="OK"',(store,)).fetchone()['c']
        derived_status = (r['status'] if r else ('READY' if fetched else 'INDEXED' if count else 'NOT_SYNCED'))
        out[store]={'status':derived_status,'indexed_urls':count,'fetched_products':fetched,'finished_at':r['finished_at'] if r else None,'age_sec':(now-r['finished_at']) if r and r['finished_at'] else None,'error':r['error'] if r else None}
    conn.close();return out

if __name__=='__main__':
    print(sync_all())

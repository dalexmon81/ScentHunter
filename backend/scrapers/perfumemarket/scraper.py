import os
import re
import time
import json
import random
import unicodedata
import difflib
import fcntl
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin, unquote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Optional imports (Playwright and Redis). Handled gracefully if missing.
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

try:
    import redis
except Exception:
    redis = None

# Configuration
BASE_URL = "https://www.perfumemarket.nl"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
DEBUG_DIR = os.getenv("PERFUME_DEBUG_DUMP_DIR", "/tmp/perfumemarket-debug")
SHARED_DIR = os.getenv("PERFUME_SHARED_DIR", "/tmp")
MIN_INTERVAL = float(os.getenv("PERFUME_RATE_MIN_INTERVAL", "2.5"))
MAX_RETRIES_429 = int(os.getenv("PERFUME_MAX_RETRIES_429", "4"))
ENABLE_PLAYWRIGHT = os.getenv("PERFUME_ENABLE_PLAYWRIGHT", "0") in ("1", "true", "True", "yes")
VERBOSE = os.getenv("PERFUME_VERBOSE", "1") in ("1", "true", "True", "yes")

# HTTP defaults
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-US,en;q=0.8"
}

# Stopwords to ignore when matching tokens (extend as needed)
IGNORED_MATCH_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "ml", "pour", "for", "the", "and", "man", "men",
    "woman", "women", "unisex", "spray", "vaporisateur", "intense", "intense.", "intense,",
}

# Price regex: euro amounts
PRICE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*€", re.I)

# Ensure debug directory
try:
    os.makedirs(DEBUG_DIR, exist_ok=True)
except Exception:
    pass

# simple logger
def log(msg):
    print(f"PERFUMEMARKET: {msg}")

def vlog(msg):
    if VERBOSE:
        log(msg)

def _debug_dump(name, text):
    try:
        safe = re.sub(r"[^0-9A-Za-z_.-]", "_", name)[:50]
        fname = os.path.join(DEBUG_DIR, f"{safe}_{int(time.time()*1000)}.txt")
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(text or "")
        vlog(f"DEBUG DUMP -> {fname}")
    except Exception as e:
        vlog(f"DEBUG DUMP ERROR: {e}")

# Tokenization and matching (inspired by ParfumZentrum)
def _tokens(text):
    """Return normalized tokens (remove accents), keep alnum sequences longer than 1 char."""
    if not text:
        return []
    text = unquote(str(text))
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    tokens = re.findall(r"[A-Za-z0-9]+", without_accents, flags=re.UNICODE)
    return [t.lower() for t in tokens if len(t) > 1]

def _query_token_set(query):
    tokens = [t for t in _tokens(query) if t not in IGNORED_MATCH_WORDS]
    if not tokens:
        tokens = _tokens(query)
    return set(tokens)

def _all_tokens_match(text, query):
    """Return True if all significant query tokens are present in text tokens (subset)."""
    qset = _query_token_set(query)
    if not qset:
        return False
    tset = set(_tokens(text))
    # if exact subset matches, good
    if qset.issubset(tset):
        return True
    # fallback: fuzzy per-token match (tolerate man/men and small typos)
    for q in qset:
        matched = False
        for t in tset:
            if q == t:
                matched = True
                break
            if q.endswith("s") and q[:-1] == t:
                matched = True
                break
            if difflib.SequenceMatcher(None, q, t).ratio() >= 0.8:
                matched = True
                break
        if not matched:
            return False
    return True

# Rate limiter (file-lock fallback; optional Redis support)
class DomainRateLimiter:
    def __init__(self, domain, min_interval=MIN_INTERVAL, shared_dir=SHARED_DIR, redis_url=None):
        self.domain = domain
        self.min_interval = float(min_interval)
        self.shared_dir = shared_dir
        self.redis_url = redis_url
        self.redis_client = None
        if redis_url and redis:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
            except Exception:
                self.redis_client = None
        safe_name = re.sub(r"[^0-9A-Za-z_.-]", "_", domain)
        self.lock_path = os.path.join(self.shared_dir, f"ratelimit_{safe_name}.lock")
        try:
            open(self.lock_path, "a").close()
        except Exception:
            pass

    def wait(self):
        jitter = random.uniform(0, 0.3)
        if self.redis_client:
            key = f"ratelimit:{self.domain}"
            while True:
                now = time.time()
                try:
                    last = self.redis_client.get(key)
                    if last is None:
                        if self.redis_client.setnx(key, str(now)):
                            self.redis_client.expire(key, int(self.min_interval*3)+5)
                            break
                        else:
                            time.sleep(0.05 + random.random()*0.05)
                            continue
                    last_ts = float(last)
                    wait_for = self.min_interval - (now - last_ts)
                    if wait_for > 0:
                        time.sleep(wait_for + jitter)
                        continue
                    self.redis_client.set(key, str(now), ex=int(self.min_interval*3)+5)
                    break
                except Exception:
                    self._file_wait(jitter)
                    return
        else:
            self._file_wait(jitter)

    def _file_wait(self, jitter):
        try:
            with open(self.lock_path, "r+") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    fh.seek(0)
                    data = fh.read().strip()
                    last_ts = float(data) if data else 0.0
                except Exception:
                    last_ts = 0.0
                now = time.time()
                wait_for = self.min_interval - (now - last_ts)
                if wait_for > 0:
                    time.sleep(wait_for + random.uniform(0, 0.3))
                fh.seek(0)
                fh.truncate()
                fh.write(str(time.time()))
                fh.flush()
                fcntl.flock(fh, fcntl.LOCK_UN)
        except Exception:
            time.sleep(self.min_interval + random.uniform(0, 0.3))

# single limiter instance
_RATE_LIMITER = DomainRateLimiter("perfumemarket.nl")

# HTTP session factory
def _create_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    retries = Retry(total=2, backoff_factor=0.2, status_forcelist=(500,502,503,504), allowed_methods=frozenset(['GET','HEAD','OPTIONS']))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

# request wrapper with rate limiting and 429 handling
def request_with_rate_limit(session, method, url, max_retries_429=MAX_RETRIES_429, **kwargs):
    attempt = 0
    base = 0.8
    while True:
        attempt += 1
        _RATE_LIMITER.wait()
        try:
            resp = session.request(method, url, **kwargs)
        except requests.RequestException as e:
            if attempt >= 3:
                raise
            time.sleep(min(2, base*(2**(attempt-1))) + random.uniform(0,0.2))
            continue
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    sleep_for = int(ra)
                except Exception:
                    try:
                        sleep_for = float(ra)
                    except Exception:
                        sleep_for = MIN_INTERVAL
                sleep_for += random.uniform(0,0.5)
                log(f"429 Retry-After {sleep_for:.1f}s for {url}")
                time.sleep(sleep_for)
                continue
            else:
                if attempt > max_retries_429:
                    _debug_dump_short(resp, "429")
                    resp.raise_for_status()
                backoff = base*(2**(attempt-1)) + random.uniform(0,0.5)
                log(f"429 backing off {backoff:.2f}s (attempt {attempt}) for {url}")
                time.sleep(backoff)
                continue
        if resp.status_code >= 500 and attempt < 3:
            time.sleep(0.5 + random.random()*0.3)
            continue
        if resp.status_code != 200:
            try:
                _debug_dump_short(resp, f"non200_{resp.status_code}")
            except Exception:
                pass
        return resp

def _debug_dump_short(resp, tag):
    try:
        text = resp.text or ""
        _debug_dump(f"{tag}_{re.sub(r'[^0-9A-Za-z_.-]','_', resp.url)[:60]}", text[:10000])
    except Exception:
        pass

# Sitemap helpers (sitemap-first approach)
def _xml_urls_from_text(xml_text):
    urls = []
    try:
        soup = BeautifulSoup(xml_text or "", "xml")
        for loc in soup.find_all("loc"):
            url = str(loc.get_text(strip=True) or "")
            if url:
                urls.append(url)
    except Exception:
        # fallback naive parse
        for m in re.finditer(r"<loc>([^<]+)</loc>", xml_text or "", re.I):
            urls.append(m.group(1).strip())
    return urls

def _get_sitemap_urls(session):
    try:
        resp = request_with_rate_limit(session, "GET", SITEMAP_URL, timeout=8)
    except Exception as e:
        vlog(f"SITEMAP GET ERROR: {e}")
        return []
    if resp.status_code in (403, 429):
        log(f"SITEMAP BLOCKED: HTTP {resp.status_code}")
        return []
    xml = resp.text
    urls = _xml_urls_from_text(xml)
    # If sitemap points to child sitemaps, expand them
    child_maps = [u for u in urls if "sitemap" in u.lower() and u.lower().endswith((".xml", ".xml.gz"))]
    if not child_maps:
        return urls
    out = []
    for sm in child_maps:
        try:
            r = request_with_rate_limit(session, "GET", sm, timeout=8)
        except Exception as e:
            vlog(f"Child sitemap GET failed: {e}")
            continue
        if r.status_code != 200 or not r.text:
            continue
        out.extend(_xml_urls_from_text(r.text))
    return out

# Parsing and extraction helpers
def _extract_price_from_text(text):
    if not text:
        return None
    m = PRICE_RE.search(text)
    if m:
        val = m.group(1)
        # Normalize: 1.234,56 -> keep comma decimal if present; convert dot thousands to empty
        val = val.replace(".", "").replace(",", ".") if "," in val and "." in val else val
        # show with comma as decimal separator in output
        val = val.replace(".", ",")
        return val + " €" if not val.endswith("€") else val
    return None

def _extract_price_from_node(node):
    if node is None:
        return None
    # Search data-attributes and itemprop
    for elem in node.find_all(True):
        for attr in ("data-price", "data-product-price", "data-final-price", "data-price-amount", "data-priceamount", "data-price-cents"):
            if elem.has_attr(attr):
                candidate = str(elem[attr]).strip()
                price = _extract_price_from_text(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
                if price:
                    return price
        if elem.has_attr("itemprop") and elem.get("itemprop", "").lower() == "price":
            candidate = elem.get("content") or elem.get_text(" ", strip=True)
            price = _extract_price_from_text(candidate)
            if price:
                return price
        class_attr = " ".join(elem.get("class") or [])
        if class_attr and re.search(r"price|prijs|kosten|product-price|final-price|price--", class_attr, re.I):
            candidate = elem.get("content") or elem.get_text(" ", strip=True)
            price = _extract_price_from_text(candidate)
            if price:
                return price
    # last resort: search visible text
    return _extract_price_from_text(node.get_text(" ", strip=True))

def _parse_search_html(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    results = []
    seen = set()
    # walk anchors
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        product_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            continue
        if product_url in seen:
            continue
        # find container/card
        card = a
        for _ in range(8):
            if card is None:
                break
            text = card.get_text(" ", strip=True)
            if len(text) >= 20:
                break
            card = getattr(card, "parent", None)
        if card is None:
            continue
        # name extraction
        name = ""
        for sel in ("h1","h2",".product-title",".product__title",".product-name"):
            try:
                el = card.select_one(sel)
            except Exception:
                el = None
            if el:
                name = el.get_text(" ", strip=True)
                break
        if not name:
            name = a.get_text(" ", strip=True)
        # match query
        if not _all_tokens_match(name + " " + card.get_text(" ", strip=True) + " " + product_url, query):
            vlog(f"SKIP_HTML_MISMATCH url={product_url} name={name[:60]!r}")
            continue
        price = _extract_price_from_node(card) or _extract_price_from_text(card.get_text(" ", strip=True))
        if not price:
            vlog(f"SKIP_HTML_NOPRICE url={product_url} name={name!r}")
            continue
        seen.add(product_url)
        results.append({"store":"PerfumeMarket","name":name,"price":price,"url":product_url})
        vlog(f"HTML_MATCH url={product_url} name={name!r} price={price}")
    return results

def _parse_search_suggest(payload, query):
    results = []
    seen = set()
    if not isinstance(payload, dict):
        return results
    resources = payload.get("resources", {}) or {}
    nested = resources.get("results", {}) or {}
    products = nested.get("products", []) or []
    for p in products:
        if not isinstance(p, dict):
            continue
        name = str(p.get("title") or p.get("name") or "").strip()
        url = str(p.get("url") or "").strip()
        vlog(f"CANDIDATE_SUGGEST name={name!r} url={url}")
        if not name or not url or not _all_tokens_match(name, query):
            vlog(f"SKIP_SUGGEST name/url/mismatch {name!r} {url}")
            continue
        product_url = urljoin(BASE_URL, url).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            vlog(f"SKIP_SUGGEST_NOT_PRODUCT {product_url}")
            continue
        price = None
        variants = p.get("variants") or []
        for v in variants:
            if isinstance(v, dict):
                raw = str(v.get("price") or "").strip()
                price = _extract_price_from_text(raw)
                if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw):
                    price = raw.replace(".", ",") + " €"
                if price:
                    break
        if not price:
            raw = str(p.get("price") or p.get("price_min") or "").strip()
            price = _extract_price_from_text(raw)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw):
                price = raw.replace(".", ",") + " €"
        if not price:
            vlog(f"SKIP_SUGGEST_NOPRICE url={product_url} name={name!r}")
            continue
        if product_url in seen:
            continue
        seen.add(product_url)
        results.append({"store":"PerfumeMarket","name":name,"price":price,"url":product_url})
        vlog(f"SUGGEST_MATCH url={product_url} name={name!r} price={price}")
    return results

def _parse_catalog_json(payload, query):
    results = []
    if not isinstance(payload, dict):
        return results
    products = payload.get("products") or []
    seen = set()
    for p in products:
        if not isinstance(p, dict):
            continue
        title = str(p.get("title") or p.get("name") or "").strip()
        handle = str(p.get("handle") or "").strip()
        if not title:
            continue
        if not _all_tokens_match(title + " " + handle.replace("-", " "), query):
            vlog(f"SKIP_CATALOG_MISMATCH title={title[:60]!r} handle={handle!r}")
            continue
        # price logic similar to earlier
        price = None
        variants = p.get("variants") or []
        for v in variants:
            if isinstance(v, dict):
                raw = str(v.get("price") or "").strip()
                if raw:
                    price = _extract_price_from_text(raw) or (raw.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw) else None)
                    if price:
                        # prefer available variants
                        if v.get("available") is True:
                            break
        if not price:
            raw = str(p.get("price") or "").strip()
            price = _extract_price_from_text(raw)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw):
                price = raw.replace(".", ",") + " €"
        if not price:
            vlog(f"SKIP_CATALOG_NOPRICE title={title!r}")
            continue
        if not handle:
            continue
        url = urljoin(BASE_URL, "/products/" + handle).rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        results.append({"store":"PerfumeMarket","name":title,"price":price,"url":url})
        vlog(f"CATALOG_MATCH url={url} title={title!r} price={price}")
    return results

def _parse_product_page(html, query, product_url):
    soup = BeautifulSoup(html or "", "html.parser")
    # extract title
    title = ""
    for sel in ("h1", "meta[property='og:title']", "title"):
        el = soup.select_one(sel)
        if not el:
            continue
        title = el.get("content") if el.name == "meta" else el.get_text(" ", strip=True)
        if title:
            break
    if not title:
        vlog(f"PAGE_NO_TITLE url={product_url}")
        return None
    # find JSON-LD price
    price = None
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for obj in objs:
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        price = _extract_price_from_text(str(offer.get("price") or ""))
                        if price:
                            break
                if price:
                    break
            if price:
                break
        if price:
            break
    if not price:
        price = _extract_price_from_node(soup)
    if not price:
        vlog(f"PAGE_NO_PRICE url={product_url} title={title!r}")
        return None
    if not _all_tokens_match(title + " " + product_url, query):
        vlog(f"PAGE_MISMATCH url={product_url} title={title!r}")
        return None
    return {"store":"PerfumeMarket","name":title,"price":price,"url":product_url}

# Playwright fallback: render search page if enabled and Playwright available
def render_search_with_playwright(query):
    if not ENABLE_PLAYWRIGHT:
        vlog("Playwright disabled")
        return None
    if sync_playwright is None:
        log("Playwright not installed in environment")
        return None
    try:
        url = BASE_URL + "/search?q=" + quote(query)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            # prime home
            page.goto(BASE_URL, timeout=15000)
            time.sleep(0.2 + random.random()*0.3)
            page.goto(url, timeout=20000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log(f"Playwright error: {e}")
        return None

# Main search flow: sitemap -> catalog.json -> suggest -> search HTML -> sitemap pages -> playwright fallback
def search(query):
    query = str(query or "").strip()
    if not query:
        return []
    session = _create_session()
    results = []
    seen = set()

    # prime home to get cookies
    try:
        r = request_with_rate_limit(session, "GET", BASE_URL, timeout=10)
        if r and r.status_code == 200:
            vlog("Primed home page for cookies")
        time.sleep(random.uniform(0.12, 0.6))
    except Exception as e:
        vlog(f"Home prime failed: {e}")

    # 1) sitemap-first: find product URLs whose handle possibly matches the query tokens
    sitemap_urls = []
    try:
        sitemap_list = _get_sitemap_urls(session)
        if sitemap_list:
            vlog(f"SITEMAP: found {len(sitemap_list)} urls")
            sitemap_urls = sitemap_list
    except Exception as e:
        vlog(f"SITEMAP ERROR: {e}")

    candidate_urls = []
    # heuristic: product URLs often include '/products/' - choose those where handle contains query tokens
    for u in sitemap_urls:
        if "/products/" not in u.lower():
            continue
        handle = u.lower().split("/products/",1)[-1].split("/",1)[0]
        # check tokens in handle (replace hyphens with spaces)
        if _all_tokens_match(handle.replace("-", " "), query):
            candidate_urls.append(u)

    vlog(f"SITEMAP candidates: {len(candidate_urls)}")

    # Limit how many sitemap product pages we fetch immediately (keep it small)
    for url in candidate_urls[:80]:
        if url in seen:
            continue
        try:
            r = request_with_rate_limit(session, "GET", url, timeout=12)
            if r.status_code != 200:
                continue
            item = _parse_product_page(r.text, query, url)
        except Exception as e:
            vlog(f"SITEMAP product GET error {e} url={url}")
            item = None
        if item:
            key = (item["name"].lower(), item["price"])
            if key not in seen:
                seen.add(key)
                results.append(item)
                vlog(f"SITEMAP_ADDED {url} -> {item['name']!r}")
        if len(results) >= 20:
            break

    # 2) catalog.json (public Shopify catalog)
    catalog_endpoints = (
        BASE_URL + "/products.json?limit=250",
        BASE_URL + "/collections/all-perfumes/products.json?limit=250",
    )
    for endpoint in catalog_endpoints:
        for page in range(1, 8):  # reduce pages to avoid heavy load
            url = endpoint + ("&page=" + str(page) if "?" in endpoint else "?page=" + str(page))
            try:
                resp = request_with_rate_limit(session, "GET", url, timeout=12)
            except Exception as e:
                vlog(f"CATALOG GET FAILED {e} -> {url}")
                break
            if resp.status_code != 200:
                break
            try:
                payload = resp.json()
            except Exception:
                _debug_dump(f"catalog_bad_json_{page}", resp.text[:10000])
                break
            items = _parse_catalog_json(payload, query)
            for it in items:
                k = (it["name"].lower(), it["price"])
                if k not in seen:
                    seen.add(k)
                    results.append(it)
                    vlog(f"CATALOG_ADD {it['url']} -> {it['name']!r}")
            # stop early if many found
            if len(results) >= 40:
                break
            # if fewer than limit, likely last page
            products = payload.get("products") or []
            if len(products) < 250:
                break
            time.sleep(0.08)
        if len(results) >= 40:
            break

    # 3) suggest.json (single call)
    try:
        suggest_url = BASE_URL + "/search/suggest.json?q=" + quote(query) + "&resources[type]=product&resources[limit]=10"
        r = request_with_rate_limit(session, "GET", suggest_url, timeout=10)
        if r.ok:
            try:
                items = _parse_search_suggest(r.json(), query)
                for it in items:
                    k = (it["name"].lower(), it["price"])
                    if k not in seen:
                        seen.add(k)
                        results.append(it)
                        vlog(f"SUGGEST_ADD {it['url']} -> {it['name']!r}")
            except Exception:
                _debug_dump("suggest_parse_error", r.text[:8000])
    except Exception as e:
        vlog(f"SUGGEST ERROR: {e}")

    # 4) search HTML (two variants)
    for url in (BASE_URL + "/search?q=" + quote(query) + "&type=product", BASE_URL + "/search?q=" + quote(query)):
        try:
            r = request_with_rate_limit(session, "GET", url, timeout=12)
            r.raise_for_status()
        except Exception as e:
            vlog(f"SEARCH HTML ERROR: {e}")
            continue
        items = _parse_search_html(r.text, query)
        for it in items:
            k = (it["name"].lower(), it["price"])
            if k not in seen:
                seen.add(k)
                results.append(it)
                vlog(f"SEARCHHTML_ADD {it['url']} -> {it['name']!r}")

    # 5) supplemental sitemap scan if still few results (scan rest of product URLs but limit)
    if len(results) < 6 and sitemap_urls:
        extra = []
        for u in sitemap_urls:
            if "/products/" in u.lower():
                extra.append(u)
        # scan up to N extra product pages but skip already considered handles
        scanned = 0
        for u in extra:
            if scanned >= 60 or len(results) >= 60:
                break
            if any(u.lower().endswith(k) for k in ["/",""]):
                pass
            if u in seen:
                continue
            try:
                r = request_with_rate_limit(session, "GET", u, timeout=12)
                if r.status_code != 200:
                    continue
                item = _parse_product_page(r.text, query, u)
                scanned += 1
            except Exception:
                item = None
            if item:
                k = (item["name"].lower(), item["price"])
                if k not in seen:
                    seen.add(k)
                    results.append(item)
                    vlog(f"SITEMAP_EXTRA_ADD {u} -> {item['name']!r}")

    # 6) Playwright fallback (if no results)
    if not results and ENABLE_PLAYWRIGHT:
        html = render_search_with_playwright(query)
        if html:
            items = _parse_search_html(html, query)
            for it in items:
                k = (it["name"].lower(), it["price"])
                if k not in seen:
                    seen.add(k)
                    results.append(it)
                    vlog(f"PLAYWRIGHT_ADD {it['url']} -> {it['name']!r}")
        else:
            vlog("Playwright rendered no HTML")

    # Final reporting
    log(f"SEARCH COMPLETE: found_total={len(results)}")
    for i, it in enumerate(results[:100], 1):
        log(f"RESULT {i}: {it.get('name')!r} | {it.get('price')} | {it.get('url')}")
    try:
        session.close()
    except Exception:
        pass
    return results

# If run as script, quick test
if __name__ == "__main__":
    tests = [
        "1 club de nuit intense man",
        "Armaf Club de Nuit Intense Man",
        "Rasasi Hawas For Him",
    ]
    for q in tests:
        log(f"Searching for: {q}")
        res = search(q)
        log(f"Results for '{q}': {len(res)} items")
        for r in res[:20]:
            log(f" - {r.get('name')} @ {r.get('price')} -> {r.get('url')}")

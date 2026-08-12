# Complete PerfumeMarket scraper with sitemap-first discovery and token-weighted scoring
# - Uses token-weighted scoring to shortlist candidates (no permissive fuzzy match).
# - For every candidate, verifies identity by fetching the product page and accepting
#   the item only if the product page title scores >= MATCH_THRESHOLD and a price is present.
# - No brand/product-specific exceptions. No new sources/fallbacks beyond existing ones.
# - Configurable via env:
#     PERFUME_RATE_MIN_INTERVAL (default 2.5)
#     PERFUME_MATCH_THRESHOLD (default 0.6)
#     PERFUME_CANDIDATE_MIN_SCORE (default 0.35)
#     PERFUME_DEBUG_DUMP_DIR, PERFUME_VERBOSE, PERFUME_ENABLE_PLAYWRIGHT
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
ENABLE_PLAYWRIGHT = os.getenv("PERFUME_ENABLE_PLAYWRIGHT", "1") in ("1", "true", "True", "yes")
VERBOSE = os.getenv("PERFUME_VERBOSE", "1") in ("1", "true", "True", "yes")
MATCH_THRESHOLD = float(os.getenv("PERFUME_MATCH_THRESHOLD", "0.6"))
CANDIDATE_MIN_SCORE = float(os.getenv("PERFUME_CANDIDATE_MIN_SCORE", "0.35"))
MAX_RENDER_PER_SEARCH = int(os.getenv("PERFUME_MAX_RENDER_PER_SEARCH", "30"))

# HTTP defaults
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-US,en;q=0.8"
}

# Words to ignore in matching (do NOT include 'man','woman','intense' etc. as per request)
IGNORED_MATCH_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "ml", "pour", "for", "the", "and"
}

# Price regex
PRICE_RE = re.compile(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*€", re.I)

# Ensure debug directory exists
try:
    os.makedirs(DEBUG_DIR, exist_ok=True)
except Exception:
    pass

# Logging helpers
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

# Tokenization & scoring (token-weighted)
def _tokens(text):
    if not text:
        return []
    text = unquote(str(text))
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    tokens = re.findall(r"[A-Za-z0-9]+", without_accents, flags=re.UNICODE)
    return [t.lower() for t in tokens if len(t) > 1]

def _query_tokens_filtered(query):
    tokens = [t for t in _tokens(query) if t not in IGNORED_MATCH_WORDS]
    if not tokens:
        tokens = _tokens(query)
    return tokens

def _compact_normalize(s):
    t = unicodedata.normalize("NFKD", str(s or "")).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^0-9a-z]+", "", t, flags=re.UNICODE)

def _token_best_match_score(q, title_tokens):
    """
    For a single query token q, return 1.0 if exact match, else fuzzy ratio clipped,
    else 0.0.
    """
    if not title_tokens:
        return 0.0
    # exact
    if q in title_tokens:
        return 1.0
    # plural/singular heuristics
    if q.endswith("s") and q[:-1] in title_tokens:
        return 1.0
    if (q + "s") in title_tokens:
        return 1.0
    # fuzzy similarity to best title token
    best = 0.0
    for t in title_tokens:
        if len(q) <= 2 or len(t) <= 2:
            continue
        r = difflib.SequenceMatcher(None, q, t).ratio()
        if r > best:
            best = r
    # clip small matches
    return best if best >= 0.6 else 0.0

def _token_weighted_score(query, text):
    """
    Compute a weighted score in [0,1] indicating how well 'text' matches the 'query'.
    Weight of a query token is proportional to its length (longer tokens are more distinctive).
    The score sums matched weights; normalized by total weight.
    """
    qtokens = _query_tokens_filtered(query)
    if not qtokens:
        return 0.0
    ttokens = set(_tokens(text))
    # weights proportional to token length
    lengths = [len(q) for q in qtokens]
    total = sum(lengths)
    if total == 0:
        return 0.0
    score = 0.0
    for q, l in zip(qtokens, lengths):
        match_value = _token_best_match_score(q, ttokens)  # in [0,1]
        score += (l / total) * match_value
    # fallback: if compact normalized query is substring of compact text, boost score to 1.0
    compact_q = _compact_normalize(" ".join(qtokens))
    compact_t = _compact_normalize(text)
    if compact_q and compact_q in compact_t:
        return 1.0
    return float(score)

# Rate limiter (file-lock fallback)
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
                            self.redis_client.expire(key, int(self.min_interval*3) + 5)
                            break
                        else:
                            time.sleep(0.05 + random.random()*0.05)
                            continue
                    last_ts = float(last)
                    wait_for = self.min_interval - (now - last_ts)
                    if wait_for > 0:
                        time.sleep(wait_for + jitter)
                        continue
                    self.redis_client.set(key, str(now), ex=int(self.min_interval*3) + 5)
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

# Request wrapper
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

# Sitemap helpers
def _xml_urls_from_text(xml_text):
    urls = []
    try:
        soup = BeautifulSoup(xml_text or "", "xml")
        for loc in soup.find_all("loc"):
            url = str(loc.get_text(strip=True) or "")
            if url:
                urls.append(url)
    except Exception:
        for m in re.finditer(r"<loc>([^<]+)</loc>", xml_text or "", re.I):
            urls.append(m.group(1).strip())
    return urls

def _get_sitemap_urls(session):
    try:
        resp = request_with_rate_limit(session, "GET", SITEMAP_URL, timeout=10)
    except Exception as e:
        vlog(f"SITEMAP GET ERROR: {e}")
        return []
    if resp.status_code in (403, 429):
        log(f"SITEMAP BLOCKED: HTTP {resp.status_code}")
        return []
    xml = resp.text
    urls = _xml_urls_from_text(xml)
    child_maps = [u for u in urls if "sitemap" in u.lower() and u.lower().endswith((".xml", ".xml.gz"))]
    if not child_maps:
        return urls
    out = []
    for sm in child_maps:
        try:
            r = request_with_rate_limit(session, "GET", sm, timeout=10)
        except Exception as e:
            vlog(f"Child sitemap GET failed: {e}")
            continue
        if r.status_code != 200 or not r.text:
            continue
        out.extend(_xml_urls_from_text(r.text))
    return out

# Price extraction utilities
def _extract_price_from_text(text):
    if not text:
        return None
    m = PRICE_RE.search(text)
    if m:
        val = m.group(1)
        # normalize thousand separators and decimal
        if "." in val and "," in val:
            val = val.replace(".", "")
        val = val.replace(".", ",")
        return val + " €" if not val.endswith("€") else val
    return None

def _extract_price_from_node(node):
    if node is None:
        return None
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
    return _extract_price_from_text(node.get_text(" ", strip=True))

# HTML parsing helpers (return preliminary candidates instead of final accept)
def _parse_search_html(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        product_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            continue
        if product_url in seen:
            continue
        # find a surrounding card/container
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
        # extract card name
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
        combined_text = f"{name} {card.get_text(' ', strip=True)} {product_url}"
        score = _token_weighted_score(query, combined_text)
        if score < CANDIDATE_MIN_SCORE:
            vlog(f"SKIP_HTML_LOW_SCORE url={product_url} name={name!r} score={score:.3f}")
            continue
        # price from card (may be None)
        price = _extract_price_from_node(card) or _extract_price_from_text(card.get_text(" ", strip=True))
        candidates.append({"source":"search_html","url":product_url,"name":name,"score":score,"price":price})
        seen.add(product_url)
        vlog(f"HTML_CANDIDATE url={product_url} name={name!r} score={score:.3f} price_in_card={'yes' if price else 'no'}")
    return candidates

def _parse_search_suggest(payload, query):
    candidates = []
    if not isinstance(payload, dict):
        return candidates
    resources = payload.get("resources", {}) or {}
    nested = resources.get("results", {}) or {}
    products = nested.get("products", []) or []
    seen = set()
    for p in products:
        if not isinstance(p, dict):
            continue
        name = str(p.get("title") or p.get("name") or "").strip()
        url = str(p.get("url") or "").strip()
        product_url = urljoin(BASE_URL, url).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            continue
        if product_url in seen:
            continue
        # compute score based on name/url
        score = _token_weighted_score(query, name + " " + product_url)
        if score < CANDIDATE_MIN_SCORE:
            vlog(f"SKIP_SUGGEST_LOW_SCORE url={product_url} name={name!r} score={score:.3f}")
            continue
        # try to get price from payload variants
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
        candidates.append({"source":"suggest","url":product_url,"name":name,"score":score,"price":price})
        seen.add(product_url)
        vlog(f"SUGGEST_CANDIDATE url={product_url} name={name!r} score={score:.3f} price_present={'yes' if price else 'no'}")
    return candidates

def _parse_catalog_json(payload, query):
    candidates = []
    if not isinstance(payload, dict):
        return candidates
    products = payload.get("products") or []
    seen = set()
    for p in products:
        if not isinstance(p, dict):
            continue
        title = str(p.get("title") or p.get("name") or "").strip()
        handle = str(p.get("handle") or "").strip()
        if not title:
            continue
        combined = title + " " + handle.replace("-", " ")
        score = _token_weighted_score(query, combined)
        if score < CANDIDATE_MIN_SCORE:
            vlog(f"SKIP_CATALOG_LOW_SCORE title={title[:60]!r} handle={handle!r} score={score:.3f}")
            continue
        # try to get price from variants
        price = None
        variants = p.get("variants") or []
        for v in variants:
            if isinstance(v, dict):
                raw = str(v.get("price") or "").strip()
                if raw:
                    price = _extract_price_from_text(raw) or (raw.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw) else None)
                    if price:
                        if v.get("available") is True:
                            break
        if not price:
            raw = str(p.get("price") or "").strip()
            price = _extract_price_from_text(raw)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw):
                price = raw.replace(".", ",") + " €"
        if not handle:
            continue
        url = urljoin(BASE_URL, "/products/" + handle).rstrip("/")
        candidates.append({"source":"catalog","url":url,"name":title,"score":score,"price":price})
        seen.add(url)
        vlog(f"CATALOG_CANDIDATE url={url} title={title!r} score={score:.3f} price_present={'yes' if price else 'no'}")
    return candidates

def _extract_trusted_price_value(value):
    """Extract a price from a trusted numeric price field (e.g. JSON-LD)."""
    raw = str(value or "").strip()
    if not raw:
        return None
    price = _extract_price_from_text(raw)
    if price:
        return price
    if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw):
        return raw.replace(".", ",") + " €"
    return None


def _page_match_signals(soup, product_url):
    """Return title-like signals from the real product page."""
    signals = []

    for selector in ("h1", "meta[property='og:title']", "title"):
        try:
            el = soup.select_one(selector)
        except Exception:
            el = None
        if not el:
            continue
        value = el.get("content") if el.name == "meta" else el.get_text(" ", strip=True)
        if value:
            signals.append((selector, str(value).strip()))

    meta_description = soup.select_one("meta[name='description']")
    if meta_description and meta_description.get("content"):
        signals.append(("meta_description", str(meta_description.get("content")).strip()))

    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objects = data if isinstance(data, list) else [data]
        stack = list(objects)
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            name = str(obj.get("name") or "").strip()
            if name:
                signals.append(("jsonld_name", name))
            graph = obj.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    # The canonical product URL is a supporting signal, not the sole identity signal.
    signals.append(("product_url", product_url))
    return signals


def _extract_page_price(soup):
    """Extract price from JSON-LD first, then trusted page elements."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        objects = data if isinstance(data, list) else [data]
        stack = list(objects)
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
                continue
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        price = _extract_trusted_price_value(offer.get("price"))
                        if price:
                            return price
            graph = obj.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    return _extract_price_from_node(soup)


def _parse_product_page(html, query, product_url):
    """
    Parse a product page and verify identity using multiple page signals.
    Price must still be present in the supplied HTML; JS rendering is handled
    separately by _verify_candidate_by_page when static price extraction fails.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    signals = _page_match_signals(soup, product_url)
    if not signals:
        vlog(f"PAGE_NO_TITLE url={product_url}")
        return None

    # Strong title-like signals are preferred. Meta description is only a
    # secondary signal; the URL is never sufficient by itself.
    strong_signals = [text for kind, text in signals if kind in ("h1", "meta[property='og:title']", "title", "jsonld_name")]
    secondary_signals = [text for kind, text in signals if kind == "meta_description"]
    strong_scores = [_token_weighted_score(query, text) for text in strong_signals]
    secondary_scores = [_token_weighted_score(query, text) for text in secondary_signals]
    page_score = max(strong_scores or [0.0])
    if page_score < MATCH_THRESHOLD and secondary_scores:
        page_score = max(page_score, max(secondary_scores))

    if page_score < MATCH_THRESHOLD:
        vlog(f"PAGE_MISMATCH url={product_url} page_score={page_score:.3f} signals={[s for _, s in signals[:5]]}")
        return None

    price = _extract_page_price(soup)
    if not price:
        vlog(f"PAGE_NO_PRICE url={product_url} page_score={page_score:.3f}")
        return None

    # Return the best strong identity signal as the displayed product name.
    best_name = strong_signals[0] if strong_signals else signals[0][1]
    best_score = -1.0
    for text in strong_signals:
        score = _token_weighted_score(query, text)
        if score > best_score:
            best_score = score
            best_name = text

    vlog(f"PAGE_MATCH url={product_url} title={best_name!r} price={price} page_score={page_score:.3f}")
    return {"store":"PerfumeMarket","name":best_name,"price":price,"url":product_url}

# Playwright product-page fallback.
def render_product_page_with_playwright(product_url):
    """Render one product page only when static HTML did not expose its price."""
    if not ENABLE_PLAYWRIGHT:
        vlog("Playwright disabled")
        return None
    if sync_playwright is None:
        log("Playwright not installed in environment")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(BASE_URL, timeout=15000)
            time.sleep(0.2 + random.random()*0.3)
            page.goto(product_url, timeout=20000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log(f"Playwright product error: {e}")
        return None


def render_search_with_playwright(query):
    """Legacy search-page rendering retained only as the final fallback."""
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


# Verify candidate by fetching product page. If the static page has no price,
# optionally render that one product page with Playwright and verify again.
def _verify_candidate_by_page(session, candidate, query, render_state=None):
    """
    candidate: dict with {url, name, score, price, source}
    render_state: mutable per-search counter for product-page renders.
    returns parsed item dict or None
    """
    url = candidate.get("url")
    try:
        resp = request_with_rate_limit(session, "GET", url, timeout=12)
    except Exception as e:
        vlog(f"VERIFY_GET_ERROR url={url} err={e}")
        return None
    if resp.status_code != 200 or not resp.text:
        vlog(f"VERIFY_GET_FAILED url={url} status={getattr(resp,'status_code',None)}")
        return None

    item = _parse_product_page(resp.text, query, url)
    if item:
        vlog(f"VERIFY_SUCCESS url={url} name={item.get('name')!r}")
        return item

    # Only render when the static page was a plausible identity but lacked a price.
    # This keeps Playwright away from the broad candidate/sitemap scan.
    static_soup = BeautifulSoup(resp.text, "html.parser")
    static_signals = _page_match_signals(static_soup, url)
    strong_signals = [text for kind, text in static_signals if kind in ("h1", "meta[property='og:title']", "title", "jsonld_name")]
    static_score = max([_token_weighted_score(query, text) for text in strong_signals] or [0.0])
    if static_score < MATCH_THRESHOLD:
        vlog(f"VERIFY_FAILED url={url} static_score={static_score:.3f}")
        return None

    if not ENABLE_PLAYWRIGHT:
        vlog(f"VERIFY_FAILED url={url} static_score={static_score:.3f} playwright=disabled")
        return None

    if render_state is None:
        render_state = {"count": 0}
    if render_state.get("count", 0) >= MAX_RENDER_PER_SEARCH:
        vlog(f"VERIFY_RENDER_LIMIT url={url} limit={MAX_RENDER_PER_SEARCH}")
        return None

    render_state["count"] = render_state.get("count", 0) + 1
    vlog(f"VERIFY_RENDER url={url} render_count={render_state['count']}/{MAX_RENDER_PER_SEARCH}")
    rendered_html = render_product_page_with_playwright(url)
    if not rendered_html:
        vlog(f"VERIFY_FAILED url={url} rendered_html=empty")
        return None

    item = _parse_product_page(rendered_html, query, url)
    if item:
        vlog(f"VERIFY_RENDER_SUCCESS url={url} name={item.get('name')!r}")
    else:
        vlog(f"VERIFY_RENDER_FAILED url={url}")
    return item

# Main search flow with candidate verification
def search(query):
    query = str(query or "").strip()
    if not query:
        return []
    session = _create_session()
    results = []
    seen = set()
    render_state = {"count": 0}

    # Prime home to get cookies
    try:
        r = request_with_rate_limit(session, "GET", BASE_URL, timeout=10)
        if r and r.status_code == 200:
            vlog("Primed home page for cookies")
        time.sleep(random.uniform(0.12, 0.6))
    except Exception as e:
        vlog(f"Home prime failed: {e}")

    # 1) sitemap-first: product pages (these are already verified by _parse_product_page)
    sitemap_urls = []
    try:
        sitemap_list = _get_sitemap_urls(session)
        if sitemap_list:
            vlog(f"SITEMAP: found {len(sitemap_list)} urls")
            sitemap_urls = sitemap_list
    except Exception as e:
        vlog(f"SITEMAP ERROR: {e}")

    product_urls = [u for u in sitemap_urls if "/products/" in u.lower()]
    vlog(f"SITEMAP product URLs: {len(product_urls)}")

    max_scan = int(os.getenv("PERFUME_SITEMAP_SCAN_LIMIT", "500"))
    scanned = 0
    for url in product_urls:
        if scanned >= max_scan or len(results) >= int(os.getenv("PERFUME_MAX_RESULTS", "200")):
            break
        try:
            resp = request_with_rate_limit(session, "GET", url, timeout=12)
        except Exception as e:
            vlog(f"SITEMAP product GET error: {e} url={url}")
            continue
        if resp.status_code != 200 or not resp.text:
            continue
        item = _parse_product_page(resp.text, query, url)
        scanned += 1
        if item:
            key = (item["name"].lower(), item["price"])
            if key not in seen:
                seen.add(key)
                results.append(item)
                vlog(f"SITEMAP_ADD {url} -> {item['name']!r}")
        time.sleep(0.05 + random.random() * 0.05)

    vlog(f"Sitemap scan complete: scanned={scanned}, matched={len(results)}")

    # Collect candidates from catalog and suggest and search-html (do NOT accept until verified)
    candidates = []

    # catalog.json
    catalog_endpoints = (
        BASE_URL + "/products.json?limit=250",
        BASE_URL + "/collections/all-perfumes/products.json?limit=250",
    )
    for endpoint in catalog_endpoints:
        for page in range(1, 8):
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
            cats = _parse_catalog_json(payload, query)
            candidates.extend(cats)
            products = payload.get("products") or []
            if len(products) < 250:
                break
            time.sleep(0.08)
        # we do not break early here; collected candidates will be verified

    # suggest.json (single call)
    try:
        suggest_url = BASE_URL + "/search/suggest.json?q=" + quote(query) + "&resources[type]=product&resources[limit]=10"
        r = request_with_rate_limit(session, "GET", suggest_url, timeout=10)
        if r.ok:
            try:
                cats = _parse_search_suggest(r.json(), query)
                candidates.extend(cats)
            except Exception:
                _debug_dump("suggest_parse_error", r.text[:8000])
    except Exception as e:
        vlog(f"SUGGEST ERROR: {e}")

    # search HTML (two variants) - collect candidates, not final accept
    for url in (BASE_URL + "/search?q=" + quote(query) + "&type=product", BASE_URL + "/search?q=" + quote(query)):
        try:
            r = request_with_rate_limit(session, "GET", url, timeout=12)
            r.raise_for_status()
        except Exception as e:
            vlog(f"SEARCH HTML ERROR: {e}")
            continue
        cats = _parse_search_html(r.text, query)
        candidates.extend(cats)

    vlog(f"Collected candidates from sources: {len(candidates)}")

    # Verify candidates by fetching product page (strong identity verification)
    # To avoid excessive load, allow limiting number of verifications (configurable)
    verify_limit = int(os.getenv("PERFUME_VERIFY_CANDIDATE_LIMIT", "120"))
    verified = 0
    # Prioritize the most relevant candidates and remove duplicate URLs before verification.
    # IMPORTANT: keep the BEST candidate for each URL, not the first one encountered.
    # The same product can be returned by catalog.json, suggest.json and search HTML
    # with different scores. Keeping the first occurrence could discard an exact
    # score=1.0 candidate before the final sort.
    best_candidate_by_url = {}
    candidates_without_url = []
    for _candidate in candidates:
        _candidate_url = _candidate.get("url")
        if not _candidate_url:
            candidates_without_url.append(_candidate)
            continue
        _score = float(_candidate.get("score", 0.0) or 0.0)
        _existing = best_candidate_by_url.get(_candidate_url)
        if _existing is None or _score > float(_existing.get("score", 0.0) or 0.0):
            best_candidate_by_url[_candidate_url] = _candidate

    ordered_candidates = list(best_candidate_by_url.values()) + candidates_without_url
    ordered_candidates.sort(key=lambda _candidate: _candidate.get("score", 0.0) or 0.0, reverse=True)
    candidates = ordered_candidates
    vlog(f"Candidates deduplicated: {len(candidates)} unique URLs")
    for _priority_candidate in candidates[:10]:
        vlog(
            f"CANDIDATE_PRIORITY url={_priority_candidate.get('url')} "
            f"score={float(_priority_candidate.get('score', 0.0) or 0.0):.3f} "
            f"source={_priority_candidate.get('source')} "
            f"price_present={'yes' if _priority_candidate.get('price') else 'no'}"
        )

    for cand in candidates:
        if verified >= verify_limit or len(results) >= int(os.getenv("PERFUME_MAX_RESULTS", "200")):
            break
        # If candidate already present in results (by url) skip
        url = cand.get("url")
        if any(url == it.get("url") for it in results):
            continue
        # If candidate already has price in payload/card, still verify by page as requested
        item = _verify_candidate_by_page(session, cand, query, render_state)
        verified += 1
        if item:
            key = (item["name"].lower(), item["price"])
            if key not in seen:
                seen.add(key)
                results.append(item)
                vlog(f"CANDIDATE_VERIFIED_ADD {url} -> {item['name']!r}")
        else:
            vlog(f"CANDIDATE_REJECTED {url} score_prelim={cand.get('score'):.3f}")

    # Supplemental sitemap scan if few results (unchanged)
    if len(results) < int(os.getenv("PERFUME_SUPPLEMENTAL_RESULTS_THRESHOLD", "4")) and product_urls:
        extra_scan_limit = int(os.getenv("PERFUME_SUPPLEMENTAL_SCAN_LIMIT", "120"))
        extra_scanned = 0
        for u in product_urls:
            if extra_scanned >= extra_scan_limit or len(results) >= int(os.getenv("PERFUME_MAX_RESULTS", "200")):
                break
            try:
                resp = request_with_rate_limit(session, "GET", u, timeout=12)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            item = _parse_product_page(resp.text, query, u)
            extra_scanned += 1
            if item:
                k = (item["name"].lower(), item["price"])
                if k not in seen:
                    seen.add(k)
                    results.append(item)
                    vlog(f"SITEMAP_EXTRA_ADD {u} -> {item['name']!r}")

    # Playwright fallback only if enabled and still no results
    if not results and ENABLE_PLAYWRIGHT:
        html = render_search_with_playwright(query)
        if html:
            items = []
            # parse rendered html for candidates and verify
            cats = _parse_search_html(html, query)
            for c in cats:
                item = _verify_candidate_by_page(session, c, query, render_state)
                if item:
                    k = (item["name"].lower(), item["price"])
                    if k not in seen:
                        seen.add(k)
                        results.append(item)
                        vlog(f"PLAYWRIGHT_VERIFIED_ADD {c['url']} -> {item['name']!r}")
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

# Local unit tests for scoring logic and sample titles (offline).
# These tests are NOT live network tests; they help verify that the token-weighted scoring
# behaves sensibly for the five requested cases.
def _unit_test_scoring():
    tests = {
        "Club de Nuit Intense Man": [
            "Armaf Club De Nuit Intense Man 105ml EDT - Men",
            "Armaf Club De Nuit Lionheart for Women 100ml EDP",
            "Armaf Club De Nuit Intense 105ml",
            "Club de Nuit Intense - 105ml edt"
        ],
        "Dior Sauvage": [
            "Dior Sauvage Eau de Toilette 100ml",
            "Sauvage Parfum 60ml Dior",
            "Dior Sauvage 200ml",
            "Sauvage - 100 ml EDT"
        ],
        "Invictus": [
            "Paco Rabanne Invictus 100ml EDT",
            "Invictus Victory 100ml",
            "Paco Rabanne Invictus Legend 100ml"
        ],
        "L'Aventure Intense": [
            "Al Haramain L'Aventure Intense 100ml EDP",
            "L'Aventure Intense 100ml",
            "L'Aventure 100ml"
        ],
        "Liquid Brun Limited Edition": [
            "Liquid Brun Limited Edition 70ml",
            "Liquid Brun 70ml",
            "Liquid Brun - Limited Edition 2024"
        ],
    }

    for query, titles in tests.items():
        print(f"\n--- TEST QUERY: {query} ---")
        for t in titles:
            s = _token_weighted_score(query, t)
            print(f"title={t!r}\n  score={s:.3f}")

if __name__ == "__main__":
    # Run local scoring tests for the requested cases
    _unit_test_scoring()
    # NOTE: To run live searches against the site, call search(query) with the queries.
    # E.g.:
    # res = search("Club de Nuit Intense Man")
    # print(res)

import json
import os
import re
import time
import random
import unicodedata
import difflib
import requests
import fcntl
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Optional: Redis shared limiter. Import only if available.
try:
    import redis
except Exception:
    redis = None

BASE_URL = "https://www.perfumemarket.nl"
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€")

# Config from env
MIN_INTERVAL = float(os.getenv("PERFUME_RATE_MIN_INTERVAL", "1.5"))  # seconds between requests to same domain
SHARED_DIR = os.getenv("PERFUME_SHARED_DIR", "/tmp")
REDIS_URL = os.getenv("PERFUME_REDIS_URL")  # e.g. redis://user:pass@host:6379/0
MAX_RETRIES_429 = int(os.getenv("PERFUME_MAX_RETRIES_429", "4"))


def log(msg):
    print(f"PERFUMEMARKET: {msg}")


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    value = match.group(1) or match.group(2)
    value = value.replace(".", ",")
    return value + " €"


def _normalize_text(s):
    if not s:
        return ""
    normalized = unicodedata.normalize("NFKD", str(s))
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    return without_accents.lower()


def _tokens(text):
    if not text:
        return []
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    tokens = re.findall(r"[0-9\w]+", without_accents, flags=re.UNICODE)
    return [t.lower().replace("_", "") for t in tokens if t.strip() and not set(t) == {"_"}]


def _normalize_for_match(s):
    t = _normalize_text(s)
    return re.sub(r"[^0-9a-z]+", "", t, flags=re.UNICODE)


def _token_fuzzy_in_set(token, text_tokens):
    if token in text_tokens:
        return True
    if token.endswith("s") and token[:-1] in text_tokens:
        return True
    if (token + "s") in text_tokens:
        return True
    try:
        matches = difflib.get_close_matches(token, list(text_tokens), n=1, cutoff=0.72)
    except Exception:
        matches = []
    if matches:
        return True
    for t in text_tokens:
        if len(token) <= 2 or len(t) <= 2:
            continue
        ratio = difflib.SequenceMatcher(None, token, t).ratio()
        if ratio >= 0.8:
            return True
    return False


def _query_matches(text, query):
    query = str(query or "")
    text = str(text or "")
    query_tokens = _tokens(query)
    if not query_tokens:
        return False
    text_tokens = set(_tokens(text))
    all_matched = True
    for token in query_tokens:
        if not token:
            continue
        if _token_fuzzy_in_set(token, text_tokens):
            continue
        all_matched = False
        break
    if all_matched:
        return True
    compact_query = _normalize_for_match(query)
    compact_text = _normalize_for_match(text)
    if compact_query and compact_query in compact_text:
        return True
    return False


def _product_name(container, fallback):
    if container is None:
        return fallback
    selectors = (
        "h1", "h2", "h3", "h4",
        ".product-title", ".product__title",
        ".product-name", ".product-card__title",
        "[class*='product-title']", "[class*='product-name']",
    )
    for selector in selectors:
        try:
            element = container.select_one(selector)
        except Exception:
            element = None
        if element:
            name = element.get_text(" ", strip=True)
            if name and len(name) <= 300:
                return name
    for element in container.find_all(["a", "img"], limit=20):
        value = (
            element.get("title")
            or element.get("aria-label")
            or element.get("alt")
            or ""
        ).strip()
        if value and _query_matches(value, fallback):
            return value
    return fallback


def _find_card(anchor):
    node = anchor
    for _ in range(8):
        if node is None:
            break
        text = node.get_text(" ", strip=True)
        if len(text) >= 20 and (_extract_price(text) or _tokens(text)):
            if len(text) <= 1800:
                return node
        node = getattr(node, "parent", None)
    return anchor.parent


def _extract_price_from_node(node):
    if node is None:
        return None
    for elem in node.find_all(True):
        for attr in ("data-price", "data-product-price", "data-final-price", "data-price-amount", "data-priceamount"):
            if elem.has_attr(attr):
                candidate = str(elem[attr]).strip()
                price = _extract_price(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
                if price:
                    return price
        if elem.has_attr("itemprop") and elem["itemprop"].lower() == "price":
            candidate = elem.get("content") or elem.get_text(" ", strip=True)
            price = _extract_price(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
            if price:
                return price
        class_attr = " ".join(elem.get("class") or [])
        if class_attr and re.search(r"price|kosten|prijs|product-price|final-price", class_attr, re.I):
            candidate = elem.get("content") or elem.get_text(" ", strip=True)
            price = _extract_price(candidate) or (candidate.replace(".", ",") + " €" if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", candidate) else None)
            if price:
                return price
    text = node.get_text(" ", strip=True)
    return _extract_price(text)


# Rate limiter implementation with Redis optional or file-based fallback
class DomainRateLimiter:
    def __init__(self, domain, min_interval=MIN_INTERVAL, shared_dir=SHARED_DIR, redis_url=REDIS_URL):
        self.domain = domain
        self.min_interval = float(min_interval)
        self.shared_dir = shared_dir
        self.redis_url = redis_url
        self.redis_client = None
        if redis_url and redis:
            try:
                self.redis_client = redis.from_url(redis_url)
                # quick ping
                self.redis_client.ping()
            except Exception:
                self.redis_client = None
        # file path for lock
        safe_name = re.sub(r"[^0-9a-zA-Z_.-]", "_", domain)
        self.lock_path = os.path.join(self.shared_dir, f"rate_limiter_{safe_name}.lock")
        # ensure lock file exists
        try:
            open(self.lock_path, "a").close()
        except Exception:
            pass

    def wait(self):
        jitter = random.uniform(0, 0.3)  # small jitter
        if self.redis_client:
            # use Redis GETSET pattern with expiry
            key = f"ratelimit:{self.domain}"
            now = time.time()
            while True:
                try:
                    last = self.redis_client.get(key)
                    if last is None:
                        # set with expiry to avoid stale keys; use setnx
                        if self.redis_client.setnx(key, str(now)):
                            self.redis_client.expire(key, int(self.min_interval * 3) + 5)
                            break
                        else:
                            time.sleep(0.05 + random.random() * 0.05)
                            continue
                    last_ts = float(last)
                    wait_for = self.min_interval - (now - last_ts)
                    if wait_for > 0:
                        sleep_for = wait_for + jitter
                        time.sleep(sleep_for)
                        now = time.time()
                        continue
                    # try to set new timestamp
                    if self.redis_client.getset(key, str(now)):
                        self.redis_client.expire(key, int(self.min_interval * 3) + 5)
                    break
                except Exception:
                    # fallback to file method if redis intermittent
                    self._file_wait(jitter)
                    return
        else:
            self._file_wait(jitter)

    def _file_wait(self, jitter):
        try:
            with open(self.lock_path, "r+") as fh:
                # exclusive lock during read/write
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
                    now = time.time()
                # write current timestamp
                fh.seek(0)
                fh.truncate()
                fh.write(str(now))
                fh.flush()
                fcntl.flock(fh, fcntl.LOCK_UN)
        except Exception:
            # last-resort sleep
            time.sleep(self.min_interval + random.uniform(0, 0.3))


# Create a limiter instance for perfumemarket
_PERFUME_LIMITER = DomainRateLimiter("perfumemarket.nl")


def request_with_rate_limit(session, method, url, max_retries_429=MAX_RETRIES_429, **kwargs):
    """
    Wrapper around session.request that respects per-domain rate limiter,
    handles 429 with Retry-After and exponential backoff with jitter.
    """
    attempt = 0
    backoff_base = 0.8
    while True:
        attempt += 1
        _PERFUME_LIMITER.wait()
        try:
            resp = session.request(method, url, **kwargs)
        except requests.RequestException as e:
            # network error: short backoff and retry a couple times
            if attempt >= 3:
                raise
            time.sleep(min(2, backoff_base * (2 ** (attempt - 1))) + random.uniform(0, 0.2))
            continue

        if resp.status_code == 429:
            # respect Retry-After if present
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    sleep_for = int(ra)
                except Exception:
                    try:
                        sleep_for = float(ra)
                    except Exception:
                        sleep_for = MIN_INTERVAL
                sleep_for = sleep_for + random.uniform(0, 0.5)
                log(f"429 Retry-After {sleep_for}s for {url}")
                time.sleep(sleep_for)
            else:
                # exponential backoff with jitter
                if attempt > max_retries_429:
                    resp.raise_for_status()  # give up
                backoff = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log(f"429 received, backing off {backoff:.2f}s (attempt {attempt}) for {url}")
                time.sleep(backoff)
            continue

        # For server errors, allow some retries
        if resp.status_code >= 500 and attempt < 3:
            time.sleep(0.5 + random.uniform(0, 0.3))
            continue

        return resp


# Create session with conservative automatic retries (but NOT for 429)
def _create_session_with_retries():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.2, status_forcelist=(500, 502, 503, 504), allowed_methods=frozenset(['GET','HEAD','OPTIONS']))
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def add_items_to_results(results, items, seen):
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").split("?", 1)[0].rstrip("/").lower()
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(item)


# --- parsing functions unchanged (kept for brevity) ---
# (I keep the previously improved parsing/matching/extraction code here)
# Insert the parsing functions: _parse_search_html, _parse_search_suggest, _parse_catalog_json,
# _find_candidates_from_catalog_json, _parse_product_sitemap_locs, _find_candidates_from_sitemap,
# _parse_product_page — same as previous file, but all HTTP GETs below will use request_with_rate_limit.

# For brevity in this display I reuse functions from earlier version — ensure they're present
# in code: the parsing helpers (_parse_search_html, _parse_search_suggest, etc.) remain as before.
# Below I'll include the key search() function where every session.get(*) is replaced.

# --- search() uses request_with_rate_limit for all HTTP calls ---
def search(query):
    # use the same parsing helpers implemented earlier in the file
    query = str(query or "").strip()
    if not query:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "en-US,en;q=0.8",
    }

    session = _create_session_with_retries()
    session.headers.update(headers)
    results = []
    seen = set()

    # 1) predictive suggest — do only one call (less chance to trigger rate limit)
    suggest_url = (
        BASE_URL
        + "/search/suggest.json?q="
        + quote(query)
        + "&resources[type]=product&resources[limit]=10"
    )
    try:
        resp = request_with_rate_limit(session, "GET", suggest_url, timeout=10)
        if resp.ok:
            try:
                items = _parse_search_suggest(resp.json(), query)
                if items:
                    log(f"FOUND {len(items)} via suggest")
                add_items_to_results(results, items, seen)
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
    except Exception as e:
        log(f"SUGGEST ERROR: {e}")

    # 2) search HTML — two variants, but respect rate limiter
    search_urls = (
        BASE_URL + "/search?q=" + quote(query) + "&type=product",
        BASE_URL + "/search?q=" + quote(query),
    )
    for url in search_urls:
        try:
            resp = request_with_rate_limit(session, "GET", url, timeout=12)
            resp.raise_for_status()
        except Exception as error:
            log(f"SEARCH HTML ERROR: {error}")
            continue
        items = _parse_search_html(resp.text, query)
        if items:
            log(f"FOUND {len(items)} via search-html ({url})")
        add_items_to_results(results, items, seen)

    # 3) catalog.json pages
    try:
        catalog_items = _find_candidates_from_catalog_json(session, query)
        if catalog_items:
            log(f"FOUND {len(catalog_items)} via catalog-json")
        add_items_to_results(results, catalog_items, seen)
    except Exception as e:
        log(f"CATALOG JSON ERROR: {e}")

    # 4) sitemap as supplement if not already many results
    if len(results) < 200:
        try:
            candidate_urls = _find_candidates_from_sitemap(session, query)
            if candidate_urls:
                log(f"FOUND {len(candidate_urls)} candidate URLs via sitemap")
            for product_url in candidate_urls:
                key = product_url.rstrip("/").lower()
                if key in seen:
                    continue
                try:
                    resp = request_with_rate_limit(session, "GET", product_url, timeout=12)
                    resp.raise_for_status()
                except Exception:
                    continue
                item = _parse_product_page(resp.text, query, product_url)
                if item:
                    add_items_to_results(results, [item], seen)
                    log(f"ADDED via sitemap: {item.get('url')}")
                if len(results) >= 400:
                    break
        except Exception as e:
            log(f"SITEMAP ERROR: {e}")

    return results


# NOTE: For the parsing helper functions referenced above (_parse_search_html, _parse_search_suggest, ...)
# copy-paste their implementations from the previous full file (they are unchanged except for HTTP calls).
# To keep this single file runnable, ensure those functions exist above or below this code block.

if __name__ == "__main__":
    # Quick manual test if run as script
    test_queries = [
        "chanel no 5",
        "l'aventure",
        "dior sauvage",
        "1 club de nuit intense man",
    ]
    for q in test_queries:
        log(f"Searching for: {q}")
        res = search(q)
        log(f"Results for '{q}': {len(res)} items")
        for r in res[:10]:
            log(f" - {r.get('name')} @ {r.get('price')} -> {r.get('url')}")

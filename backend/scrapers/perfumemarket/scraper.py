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

# Optional imports (Playwright and Redis). Handled gracefully if missing.
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

try:
    import redis
except Exception:
    redis = None

BASE_URL = "https://www.perfumemarket.nl"
PRICE_RE = re.compile(r"€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€")

# Config via environment
MIN_INTERVAL = float(os.getenv("PERFUME_RATE_MIN_INTERVAL", "2.5"))  # default safer interval
SHARED_DIR = os.getenv("PERFUME_SHARED_DIR", "/tmp")
REDIS_URL = os.getenv("PERFUME_REDIS_URL")  # optional
MAX_RETRIES_429 = int(os.getenv("PERFUME_MAX_RETRIES_429", "4"))
DEBUG_DUMP_DIR = os.getenv("PERFUME_DEBUG_DUMP_DIR", "/tmp/perfumemarket-debug")
ENABLE_PLAYWRIGHT = os.getenv("PERFUME_ENABLE_PLAYWRIGHT", "0") in ("1", "true", "True", "yes")
VERBOSE = os.getenv("PERFUME_VERBOSE", "1") in ("1", "true", "True", "yes")  # default on for diagnostics


def ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


ensure_dir(DEBUG_DUMP_DIR)
ensure_dir(SHARED_DIR)


def log(msg):
    print(f"PERFUMEMARKET: {msg}")


def vlog(msg):
    if VERBOSE:
        log(msg)


def _debug_dump_text(label, text):
    """Save debug text bodies to files with timestamp."""
    try:
        safe_label = re.sub(r"[^0-9A-Za-z_.-]", "_", label)[:64]
        ts = int(time.time() * 1000)
        fname = os.path.join(DEBUG_DUMP_DIR, f"{safe_label}_{ts}.txt")
        with open(fname, "w", encoding="utf-8") as fh:
            fh.write(text or "")
        vlog(f"DEBUG DUMP: saved {label} -> {fname}")
    except Exception as e:
        log(f"DEBUG DUMP ERROR: {e}")


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


# Rate limiter with optional Redis or file-lock fallback
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
                self.redis_client.ping()
            except Exception:
                self.redis_client = None
        safe_name = re.sub(r"[^0-9a-zA-Z_.-]", "_", domain)
        self.lock_path = os.path.join(self.shared_dir, f"rate_limiter_{safe_name}.lock")
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
                            self.redis_client.expire(key, int(self.min_interval * 3) + 5)
                            break
                        else:
                            time.sleep(0.05 + random.random() * 0.05)
                            continue
                    last_ts = float(last)
                    wait_for = self.min_interval - (now - last_ts)
                    if wait_for > 0:
                        time.sleep(wait_for + jitter)
                        continue
                    self.redis_client.set(key, str(now), ex=int(self.min_interval * 3) + 5)
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


_PERFUME_LIMITER = DomainRateLimiter("perfumemarket.nl")


def request_with_rate_limit(session, method, url, max_retries_429=MAX_RETRIES_429, **kwargs):
    attempt = 0
    backoff_base = 0.8
    while True:
        attempt += 1
        _PERFUME_LIMITER.wait()
        try:
            resp = session.request(method, url, **kwargs)
        except requests.RequestException as e:
            if attempt >= 3:
                raise
            time.sleep(min(2, backoff_base * (2 ** (attempt - 1))) + random.uniform(0, 0.2))
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
                sleep_for = sleep_for + random.uniform(0, 0.5)
                log(f"429 Retry-After {sleep_for}s for {url}")
                time.sleep(sleep_for)
            else:
                if attempt > max_retries_429:
                    try:
                        _debug_dump_text("429_body", resp.text[:2000])
                    except Exception:
                        pass
                    resp.raise_for_status()
                backoff = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                log(f"429 received, backing off {backoff:.2f}s (attempt {attempt}) for {url}")
                time.sleep(backoff)
            continue

        if resp.status_code >= 500 and attempt < 3:
            time.sleep(0.5 + random.uniform(0, 0.3))
            continue

        if resp.status_code != 200:
            try:
                _debug_dump_text(f"non200_{resp.status_code}_{quote(url, safe='')}", resp.text[:5000])
            except Exception:
                pass

        return resp


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
            vlog(f"SKIP add: already seen or invalid url -> {url}")
            continue
        seen.add(url)
        results.append(item)
        vlog(f"ADDED item: {item.get('name')!r} -> {url}")


# Parsing helpers with detailed diagnostics
def _parse_search_html(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    results = []
    seen = set()
    candidate_count = 0
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        product_url = urljoin(BASE_URL, href).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            continue
        if product_url in seen:
            continue
        candidate_count += 1
        card = _find_card(link)
        if card is None:
            vlog(f"SKIP candidate (no card) url={product_url}")
            continue
        card_text = card.get_text(" ", strip=True)
        name = _product_name(card, link.get_text(" ", strip=True))

        # Diagnostics: show candidate brief
        vlog(f"CANDIDATE_HTML url={product_url} name_snippet={name[:60]!r}")

        # match the query against the complete product card/name/url
        if not _query_matches(f"{name} {card_text} {product_url}", query):
            vlog(f"SKIP candidate (query mismatch) url={product_url} name={name!r}")
            continue

        # Try multiple ways to get price: from data attributes, special classes, visible text
        price = _extract_price_from_node(card)
        if not price:
            price = _extract_price(card_text)
        if not price:
            vlog(f"SKIP candidate (no price) url={product_url} name={name!r} card_text_snippet={card_text[:120]!r}")
            continue

        key = product_url.lower()
        seen.add(key)

        results.append({
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url,
        })
        vlog(f"PARSED_HTML_MATCH url={product_url} name={name!r} price={price}")
    vlog(f"HTML parse: inspected candidates={candidate_count}, matched={len(results)}")
    return results


def _parse_search_suggest(payload, query):
    results = []
    seen = set()
    resources = payload.get("resources", {}) if isinstance(payload, dict) else {}
    nested = resources.get("results", {}) if isinstance(resources, dict) else {}
    products = nested.get("products", []) if isinstance(nested, dict) else []
    if not isinstance(products, list):
        return results
    for product in products:
        if not isinstance(product, dict):
            continue
        name = str(product.get("title") or product.get("name") or "").strip()
        url = str(product.get("url") or "").strip()
        vlog(f"CANDIDATE_SUGGEST name={name!r} url={url}")
        if not name or not url or not _query_matches(name, query):
            vlog(f"SKIP suggest (name/url/mismatch) name={name!r} url={url}")
            continue
        product_url = urljoin(BASE_URL, url).split("?")[0].rstrip("/")
        if "/products/" not in product_url.lower():
            vlog(f"SKIP suggest (not product path) url={product_url}")
            continue
        price = None
        variants = product.get("variants")
        if isinstance(variants, list):
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                raw_variant_price = str(variant.get("price") or "").strip()
                price = _extract_price(raw_variant_price)
                if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_variant_price):
                    price = raw_variant_price.replace(".", ",") + " €"
                if price:
                    break
        if not price:
            raw_product_price = str(product.get("price") or product.get("price_min") or "").strip()
            price = _extract_price(raw_product_price)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_product_price):
                price = raw_product_price.replace(".", ",") + " €"
        if not price:
            vlog(f"SKIP suggest (no price) url={product_url} name={name!r}")
            continue
        key = product_url.lower()
        if key in seen:
            vlog(f"SKIP suggest (dupe) url={product_url}")
            continue
        seen.add(key)
        results.append({
            "store": "PerfumeMarket",
            "name": name,
            "price": price,
            "url": product_url,
        })
        vlog(f"PARSED_SUGGEST_MATCH url={product_url} name={name!r} price={price}")
    return results


def _parse_catalog_json(payload, query):
    if not isinstance(payload, dict):
        return []
    products = payload.get("products")
    if not isinstance(products, list):
        return []
    results = []
    seen = set()
    for product in products:
        if not isinstance(product, dict):
            continue
        title = str(product.get("title") or product.get("name") or "").strip()
        handle = str(product.get("handle") or "").strip()
        # diagnostic
        if title:
            vlog(f"CANDIDATE_CATALOG title={title[:60]!r} handle={handle!r}")
        if not title or not _query_matches(title + " " + handle.replace("-", " "), query):
            vlog(f"SKIP catalog (query mismatch) title={title!r} handle={handle!r}")
            continue
        product_id = str(product.get("id") or handle or title).strip().lower()
        if product_id in seen:
            vlog(f"SKIP catalog (dupe id) id={product_id}")
            continue
        variants = product.get("variants")
        if not isinstance(variants, list):
            variants = []
        price = None
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            raw_price = str(variant.get("price") or "").strip()
            if not raw_price:
                continue
            price = _extract_price(raw_price)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_price):
                price = raw_price.replace(".", ",") + " €"
            if price:
                if variant.get("available") is True:
                    break
        if not price:
            raw_price = str(product.get("price") or "").strip()
            price = _extract_price(raw_price)
            if not price and re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_price):
                price = raw_price.replace(".", ",") + " €"
        if not price:
            vlog(f"SKIP catalog (no price) title={title!r} handle={handle!r}")
            continue
        if handle:
            product_url = urljoin(BASE_URL, "/products/" + handle).rstrip("/")
        else:
            vlog(f"SKIP catalog (no handle) title={title!r}")
            continue
        seen.add(product_id)
        results.append({
            "store": "PerfumeMarket",
            "name": title,
            "price": price,
            "url": product_url,
        })
        vlog(f"PARSED_CATALOG_MATCH url={product_url} title={title!r} price={price}")
    return results


def _find_candidates_from_catalog_json(session, query):
    endpoints = (
        BASE_URL + "/products.json?limit=250",
        BASE_URL + "/collections/all-perfumes/products.json?limit=250",
    )
    matches = []
    seen = set()
    for base_endpoint in endpoints:
        for page in range(1, 21):
            separator = "&" if "?" in base_endpoint else "?"
            url = base_endpoint + separator + "page=" + str(page)
            try:
                resp = request_with_rate_limit(session, "GET", url, timeout=12)
            except Exception as e:
                log(f"CATALOG JSON REQUEST ERROR: {e}")
                break
            if resp.status_code != 200 or not resp.text:
                vlog(f"CATALOG endpoint returned {resp.status_code} or empty body for {url}")
                break
            try:
                payload = resp.json()
            except (ValueError, TypeError, json.JSONDecodeError):
                _debug_dump_text("catalog_json_bad_json", resp.text[:4000])
                break
            products = payload.get("products") if isinstance(payload, dict) else None
            if not isinstance(products, list) or not products:
                break
            for item in _parse_catalog_json(payload, query):
                key = item["url"].rstrip("/").lower()
                if key in seen:
                    continue
                seen.add(key)
                matches.append(item)
            if len(products) < 250:
                break
            if len(matches) >= 200:
                return matches
            time.sleep(0.08)
    vlog(f"CATALOG scan: found candidates={len(matches)}")
    return matches


def _parse_product_sitemap_locs(xml_text, query):
    if not xml_text:
        return []
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return []
    soup = BeautifulSoup(xml_text, "xml")
    urls = []
    seen = set()
    for loc in soup.find_all("loc"):
        url = str(loc.get_text(strip=True) or "")
        if "/products/" not in url.lower():
            continue
        handle = url.lower().split("/products/", 1)[-1]
        if not _query_matches(handle.replace("-", " "), query):
            continue
        clean = url.split("?", 1)[0].rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls


def _find_candidates_from_sitemap(session, query):
    try:
        resp = request_with_rate_limit(session, "GET", BASE_URL + "/sitemap.xml", timeout=10)
        if resp.status_code != 200 or not resp.text:
            vlog(f"SITEMAP root returned {resp.status_code}")
            return []
    except Exception:
        return []
    soup = BeautifulSoup(resp.text, "xml")
    sitemap_urls = []
    for loc in soup.find_all("loc"):
        url = str(loc.get_text(strip=True) or "")
        if "sitemap_products_" in url.lower():
            sitemap_urls.append(url)
    matches = []
    seen = set()
    for sitemap_url in sitemap_urls:
        try:
            resp = request_with_rate_limit(session, "GET", sitemap_url, timeout=10)
        except Exception:
            continue
        if resp.status_code != 200 or not resp.text:
            continue
        for url in _parse_product_sitemap_locs(resp.text, query):
            key = url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            matches.append(url)
            if len(matches) >= 200:
                return matches
        time.sleep(0.03)
    vlog(f"SITEMAP scan: found candidates={len(matches)}")
    return matches


def _parse_product_page(html, query, product_url):
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    for selector in ("h1", "meta[property='og:title']", "title"):
        element = soup.select_one(selector)
        if not element:
            continue
        title = (
            element.get("content", "")
            if element.name == "meta"
            else element.get_text(" ", strip=True)
        ).strip()
        if title:
            break
    if not title:
        vlog(f"PARSE PAGE SKIP (no title) url={product_url}")
        return None
    price = None
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        objects = data if isinstance(data, list) else [data]
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                continue
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = _extract_price(str(offer.get("price") or ""))
                if not price:
                    raw_price = str(offer.get("price") or "").strip()
                    if re.fullmatch(r"\d{1,5}(?:[.,]\d{2})?", raw_price):
                        price = raw_price.replace(".", ",") + " €"
                if price:
                    break
            if price:
                break
        if price:
            break
    if not price:
        price = _extract_price_from_node(soup)
    if not price:
        price = _extract_price(soup.get_text(" ", strip=True))
    if not price:
        vlog(f"PARSE PAGE SKIP (no price) url={product_url} title={title!r}")
        return None
    if not _query_matches(title + " " + product_url, query):
        vlog(f"PARSE PAGE SKIP (query mismatch) url={product_url} title={title!r}")
        return None
    vlog(f"PARSE PAGE MATCH url={product_url} title={title!r} price={price}")
    return {
        "store": "PerfumeMarket",
        "name": title,
        "price": price,
        "url": product_url,
    }


# Playwright fallback: render search page if enabled and Playwright available
def render_search_with_playwright(query):
    if not ENABLE_PLAYWRIGHT:
        vlog("Playwright fallback disabled by env")
        return None
    if sync_playwright is None:
        vlog("Playwright not installed")
        return None
    try:
        url = BASE_URL + "/search?q=" + quote(query)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
            ))
            page.goto(BASE_URL, timeout=15000)
            page.wait_for_timeout(200 + random.randint(0, 300))
            page.goto(url, timeout=20000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        log(f"Playwright render error: {e}")
        return None


def search(query):
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
        "Referer": BASE_URL,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    session = _create_session_with_retries()
    session.headers.update(headers)
    results = []
    seen = set()

    # Prime the domain (get cookies/session) - often reduces bot blocks
    try:
        resp = request_with_rate_limit(session, "GET", BASE_URL, timeout=10)
        if resp and resp.status_code == 200:
            vlog("Primed home page for cookies")
        time.sleep(random.uniform(0.15, 0.6))
    except Exception as e:
        log(f"Priming home page failed: {e}")

    # 1) predictive suggest - single call to reduce rate usage
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
            except Exception:
                _debug_dump_text("suggest_parse_error", resp.text[:5000])
    except Exception as e:
        log(f"SUGGEST ERROR: {e}")

    # 2) HTML search (two variants)
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

    # 3) Public catalog JSON
    try:
        catalog_items = _find_candidates_from_catalog_json(session, query)
        if catalog_items:
            log(f"FOUND {len(catalog_items)} via catalog-json")
        add_items_to_results(results, catalog_items, seen)
    except Exception as e:
        log(f"CATALOG JSON ERROR: {e}")

    # 4) Sitemap supplement if not many results
    if len(results) < 200:
        try:
            candidate_urls = _find_candidates_from_sitemap(session, query)
            if candidate_urls:
                log(f"FOUND {len(candidate_urls)} candidate URLs via sitemap")
            for product_url in candidate_urls:
                key = product_url.rstrip("/").lower()
                if key in seen:
                    vlog(f"SKIP sitemap (already seen) url={product_url}")
                    continue
                try:
                    resp = request_with_rate_limit(session, "GET", product_url, timeout=12)
                    resp.raise_for_status()
                except Exception:
                    vlog(f"SITEMAP product GET failed url={product_url}")
                    continue
                item = _parse_product_page(resp.text, query, product_url)
                if item:
                    add_items_to_results(results, [item], seen)
                else:
                    vlog(f"SITEMAP product parsed but no item matched url={product_url}")
                if len(results) >= 400:
                    break
        except Exception as e:
            log(f"SITEMAP ERROR: {e}")

    # 5) Playwright fallback if nothing found and enabled
    if not results:
        html = render_search_with_playwright(query)
        if html:
            items = _parse_search_html(html, query)
            if items:
                log(f"FOUND {len(items)} via playwright-render")
                add_items_to_results(results, items, seen)
            else:
                _debug_dump_text("playwright_render_html", html[:20000])

    # Final diagnostics
    log(f"SEARCH COMPLETE: found_total={len(results)}")
    for idx, it in enumerate(results, 1):
        log(f"RESULT {idx}: {it.get('name')!r} | {it.get('price')} | {it.get('url')}")

    return results


if __name__ == "__main__":
    # Quick manual test
    tests = [
        "chanel no 5",
        "l'aventure",
        "dior sauvage",
        "1 club de nuit intense man",
    ]
    for q in tests:
        log(f"Searching for: {q}")
        res = search(q)
        log(f"Results for '{q}': {len(res)} items")
        for r in res[:20]:
            log(f" - {r.get('name')} @ {r.get('price')} -> {r.get('url')}")

import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
CATALOG_URL = BASE + "/collections/produkte"
TIMEOUT = 4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

HAWAS_MAX_CATALOG_PAGES = 35
HAWAS_CATALOG_URL = BASE + "/collections/all-products"
HAWAS_WORKERS = 8


def _norm(v):
    v = str(v or "").lower()
    v = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", v)
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def _is_hawas_query(query):
    return "hawas" in set(_norm(query).split())


def _match(text, query):
    words = _norm(query).split()
    hay = _norm(text)

    # Hawas is a family query. Bplatz product titles are not guaranteed
    # to include the manufacturer ("Rasasi"), while the family name
    # "Hawas" is the reliable discovery token. Once an offer is found,
    # ProductMatcher resolves the exact Hawas variant centrally.
    if _is_hawas_query(query):
        return "hawas" in hay.split()

    return bool(words) and all(w in hay for w in words)


def _price(text):
    if not text:
        return None
    # Prefer "retail price", which is the actual selling price on Bplatz cards.
    patterns = [
        r"retail\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"sale\s+price\s*€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)",
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = m.group(1).replace(".", ",")
            try:
                if float(value.replace(",", ".")) <= 0:
                    continue
            except ValueError:
                continue
            return value + " €"
    return None


def _product_card(a):
    node = a
    best = a
    for _ in range(8):
        parent = node.parent
        if not isinstance(parent, Tag):
            break
        text = " ".join(parent.stripped_strings)
        if len(text) > 1500:
            break
        best = parent
        if "€" in text and ("Add to" in text or "Wishlist" in text or "retail price" in text.lower()):
            return parent
        node = parent
    return best


def _extract_page(html, query):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE, a["href"]).split("#")[0]
        path = href.lower()

        # Bplatz is Shopify: real product URLs use /products/ (case-insensitive).
        if "/products/" not in path:
            continue

        name = " ".join(a.stripped_strings).strip()
        title = (a.get("title") or "").strip()
        card = _product_card(a)
        card_text = " ".join(card.stripped_strings).strip()

        # Product name can be in the anchor, title, image alt or card.
        img = card.find("img")
        img_alt = (img.get("alt") or "").strip() if img else ""

        candidates = [name, title, img_alt]
        product_name = next((x for x in candidates if x and _match(x, query)), None)
        if not product_name:
            # Find a nearby link in the same card whose text is the product title.
            for pa in card.find_all("a", href=True):
                txt = " ".join(pa.stripped_strings).strip()
                phref = urljoin(BASE, pa["href"])
                if "/products/" in phref.lower() and txt and _match(txt, query):
                    product_name = txt
                    href = phref.split("#")[0]
                    break
        if not product_name:
            continue

        price = _price(card_text)
        if not price:
            continue

        key = (href, _norm(product_name))
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": href,
        })

    return out


def _fetch_hawas_page(page):
    url = HAWAS_CATALOG_URL
    try:
        r = requests.get(
            url,
            params={"page": page},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if r.status_code != 200:
            return []
        return _extract_page(r.text, "Rasasi Hawas")
    except requests.RequestException:
        return []



def _absolute_product_url(value):
    value = str(value or '').strip()
    if not value:
        return ''
    return urljoin(BASE + '/', value).split('#')[0]


def _product_js_url(product_url):
    parsed = product_url.rstrip('/')
    if parsed.endswith('.js'):
        return parsed
    return parsed + '.js'


def _shopify_price(value):
    if value in (None, ''):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # Shopify product.js normally returns prices in cents.
    if number >= 100:
        number /= 100.0
    if number <= 0:
        return None
    return f'{number:.2f}'.replace('.', ',') + ' €'


def predictive_products(session, query):
    """Return Shopify predictive-search product candidates.

    This function intentionally exists because backend/sitecustomize.py used
    to install a Bplatz streaming adapter that calls it. Defining the
    production-compatible function here makes the scraper self-contained and
    prevents the old adapter from replacing this implementation.
    """
    endpoint = BASE + '/search/suggest.json'
    params = {
        'q': query,
        'resources[type]': 'product',
        'resources[limit]': '50',
        'resources[options][unavailable_products]': 'show',
    }
    try:
        response = session.get(
            endpoint,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code != 200:
            return []
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []

    products = (
        payload.get('resources', {})
        .get('results', {})
        .get('products', [])
    )
    if not isinstance(products, list):
        return []

    candidates = []
    seen = set()
    for item in products:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        url = _absolute_product_url(item.get('url') or '')
        handle = str(item.get('handle') or '').strip()
        if not url and handle:
            url = BASE + '/products/' + handle.strip('/')
        if not title or not url or '/products/' not in url.lower():
            continue
        if not _match(title, query):
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append({
            'title': title,
            'url': url,
            'handle': handle,
            'raw': item,
        })
    return candidates


def product_worker(candidate, query):
    """Fetch one Shopify product JSON and return a normal ScentHunter row."""
    if not isinstance(candidate, dict):
        return []
    url = _absolute_product_url(candidate.get('url') or '')
    if not url:
        return []

    try:
        response = requests.get(
            _product_js_url(url),
            headers={**HEADERS, 'Accept': 'application/json,text/plain,*/*'},
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code != 200:
            return []
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    title = str(data.get('title') or candidate.get('title') or '').strip()
    if not title or not _match(title, query):
        return []

    # Do not return non-fragrance product pages accidentally matched by a
    # broad family term.
    lowered = _norm(title)
    if any(term in lowered for term in (
        'gift card', 'giftcard', 'candle', 'diffuser', 'room spray',
        'body lotion', 'body cream', 'shower gel', 'shampoo',
        'conditioner', 'deodorant', 'after shave', 'aftershave',
        'soap', 'hand cream',
    )):
        return []

    variants = data.get('variants') or []
    if not isinstance(variants, list):
        variants = []

    brand = str(data.get('vendor') or data.get('brand') or '').strip()
    rows = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        price = _shopify_price(variant.get('price'))
        if not price:
            continue
        # Keep unavailable variants only when Shopify does not expose an
        # explicit availability flag. This mirrors the scraper's role as a
        # price source without inventing stock state.
        if variant.get('available') is False:
            continue
        row = {
            'store': STORE,
            'name': title,
            'price': price,
            'url': url,
        }
        if brand:
            row['brand'] = brand
        size = str(variant.get('title') or '').strip()
        if size and size.lower() not in {'default title', 'default'}:
            row['variant'] = size
        rows.append(row)

    return rows


def search_stream(query, emit):
    """Native streaming entry point used by ScentHunter main.py."""
    query = str(query or '').strip()
    if not query:
        return None

    session = requests.Session()
    try:
        candidates = predictive_products(session, query)
    finally:
        session.close()

    # Predictive search is the primary discovery path. It is much more
    # reliable than guessing Shopify pagination URLs, whose collection path
    # changes on Bplatz (e.g. /collections/Products-a?page=2).
    if not candidates and _is_hawas_query(query):
        # Last-resort fallback: crawl the real collection pagination starting
        # from page 1 and follow the pagination URLs published by the site.
        candidates = _discover_hawas_from_pagination(query)

    if not candidates:
        return None

    with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
        futures = [pool.submit(product_worker, candidate, query) for candidate in candidates]
        for future in as_completed(futures):
            try:
                rows = future.result() or []
            except Exception:
                continue
            for row in rows:
                if isinstance(row, dict):
                    emit(row)
    return None


def _discover_hawas_from_pagination(query):
    """Fallback discovery that follows Bplatz's own pagination hrefs."""
    try:
        response = requests.get(
            CATALOG_URL,
            params={'page': 1},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, 'html.parser')
    except requests.RequestException:
        return []

    page_urls = {}
    for a in soup.find_all('a', href=True):
        href = urljoin(BASE, a.get('href', '')).split('#')[0]
        match = re.search(r'[?&]page=(\d+)', href, re.I)
        if not match:
            continue
        page = int(match.group(1))
        if 1 <= page <= 60:
            page_urls[page] = href
    page_urls[1] = response.url.split('#')[0]

    if not page_urls:
        page_urls = {1: CATALOG_URL + '?page=1'}

    candidates = []
    seen = set()

    def fetch(url):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                return []
            return _extract_page(r.text, query)
        except requests.RequestException:
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, url) for _, url in sorted(page_urls.items())]
        for future in as_completed(futures):
            for item in future.result() or []:
                if item['url'] in seen:
                    continue
                seen.add(item['url'])
                candidates.append({
                    'title': item['name'],
                    'url': item['url'],
                    'handle': '',
                })
    return candidates[:50]

def search(query):
    query = str(query or '').strip()
    if not query:
        return []

    results = []
    seen = set()

    def emit(row):
        if not isinstance(row, dict):
            return
        key = (row.get('url'), row.get('name'), row.get('price'))
        if key in seen:
            return
        seen.add(key)
        results.append(row)

    search_stream(query, emit)
    results.sort(key=lambda x: (len(_norm(x.get('name', ''))), x.get('name', '')))
    return results[:50 if _is_hawas_query(query) else 20]


if __name__ == "__main__":
    for q in ("Rasasi Hawas", "Armaf Club de Nuit", "Riiffs"):
        print("\n" + "=" * 60)
        print("QUERY:", q)
        items = search(q)
        print("RISULTATI:", len(items))
        for item in items:
            print(item)

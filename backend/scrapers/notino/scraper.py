from __future__ import annotations
import json
import logging
import os
import re
from urllib.parse import quote_plus, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None
STORE = 'Notino'
BASE_URL = 'https://www.notino.fr'
SEARCH_URL = f'{BASE_URL}/search.asp?exps={{query}}'
TIMEOUT = int(os.getenv('NOTINO_TIMEOUT_S', '15'))
DEFAULT_TIMEOUT_MS = int(os.getenv('NOTINO_TIMEOUT_MS', '30000'))
BROWSER_ENABLED = os.getenv('NOTINO_BROWSER', '1').lower() not in {'0', 'false', 'no'}
LOGGER = logging.getLogger(__name__)
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36', 'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.7'}
PRICE_RE = re.compile('(?<![\\d.,])((?:\\d{1,3}(?:[ .]\\d{3})+|\\d+)(?:[,.]\\d{2})?)\\s*(?:€|EUR)(?!\\w)', re.I)
PRODUCT_PATH_EXCLUSIONS = {'search.asp', 'parfums', 'parfums-homme', 'parfums-femme', 'cosmetiques', 'maquillage', 'cheveux', 'corps', 'visage', 'promotions', 'nouveaux', 'marques', 'panier', 'checkout', 'login', 'account', 'magazine', 'contact'}
OUT_OF_STOCK_TERMS = ('rupture de stock', 'en rupture', 'indisponible', 'épuisé', 'epuise', 'out of stock', 'sold out', 'unavailable')
IN_STOCK_TERMS = ('en stock', 'disponible', 'available', 'in stock')

def clean(value):
    return re.sub('\\s+', ' ', str(value or '')).strip()

def norm(value):
    return re.sub('\\s+', ' ', re.sub('[^a-z0-9]+', ' ', clean(value).lower())).strip()

def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}

def matches(text, query):
    query_tokens = tokens(query)
    return bool(query_tokens) and query_tokens.issubset(tokens(text))

def size_ml(*values):
    text = ' '.join((clean(x) for x in values))
    match = re.search('(?<!\\d)(\\d+(?:[.,]\\d+)?)\\s*(ml|cl)\\b', text, re.I)
    if not match:
        return None
    number = float(match.group(1).replace(',', '.'))
    if match.group(2).lower() == 'cl':
        number *= 10
    return int(number) if number.is_integer() else number

def concentration(*values):
    text = norm(' '.join((clean(x) for x in values)))
    if re.search('\\beau de toilette\\b|\\bedt\\b', text):
        return 'Eau de Toilette'
    if re.search('\\beau de parfum\\b|\\bedp\\b', text):
        return 'Eau de Parfum'
    if re.search('\\bextrait(?: de parfum)?\\b', text):
        return 'Extrait de Parfum'
    if re.search('\\bparfum\\b', text):
        return 'Parfum'
    return None

def _source_value(value, source):
    if value in (None, ''):
        return None
    return {'value': value, 'source': source}

def parse_price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
            return round(number, 2) if number > 0 else None
        except (TypeError, ValueError):
            return None
    text = clean(value)
    if not text:
        return None
    match = PRICE_RE.search(text)
    if match:
        raw = match.group(1).replace(' ', '')
    else:
        # Structured sources sometimes expose a bare numeric price.
        bare = re.fullmatch(r'\d+(?:[.,]\d{1,2})?', text)
        if not bare:
            return None
        raw = bare.group(0)
    if raw.count('.') > 1:
        raw = raw.replace('.', '')
    elif '.' in raw and ',' not in raw:
        raw = raw.replace('.', ',')
    try:
        number = float(raw.replace(',', '.'))
        return round(number, 2) if number > 0 else None
    except ValueError:
        return None

def _extract_prices(text):
    values = []
    for match in PRICE_RE.finditer(clean(text)):
        value = parse_price(match.group(0))
        if value is not None:
            values.append(value)
    return values

def availability_from_sources(data, soup):
    """Prefer structured availability; never classify from unrelated page text."""
    offers = data.get('offers') if isinstance(data, dict) else None
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            raw = offer.get('availability') or offer.get('availabilityStatus') or offer.get('stock')
            if not raw:
                continue
            text = norm(raw)
            if any((term in text for term in ('instock', 'in stock', 'available', 'disponible', 'en stock'))):
                return 'in_stock'
            if any((term in text for term in ('outofstock', 'out of stock', 'soldout', 'sold out', 'unavailable', 'not available', 'indisponible', 'rupture', 'epuise', 'épuisé'))):
                return 'out_of_stock'
    for tag in soup.select('[itemprop="availability"], meta[property="product:availability"], meta[name="availability"]'):
        raw = tag.get('content') or tag.get_text(' ', strip=True)
        text = norm(raw)
        if any((term in text for term in IN_STOCK_TERMS)):
            return 'in_stock'
        if any((term in text for term in OUT_OF_STOCK_TERMS)):
            return 'out_of_stock'
    return 'unknown'

def _normalise_url(href):
    if not href:
        return None
    href = clean(href)
    if href.startswith('//'):
        href = 'https:' + href
    elif href.startswith('/'):
        href = urljoin(BASE_URL, href)
    parsed = urlparse(href)
    if parsed.scheme not in {'http', 'https'}:
        return None
    if parsed.netloc.lower() not in {'notino.fr', 'www.notino.fr'}:
        return None
    path = parsed.path.rstrip('/')
    if not path or path == '/':
        return None
    if path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.svg')):
        return None
    return f'{parsed.scheme}://{parsed.netloc}{path}'

def _looks_like_product_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip('/').lower()
    if not path:
        return False
    if 'search.asp' in path:
        return False
    first_segment = path.split('/', 1)[0]
    if first_segment in PRODUCT_PATH_EXCLUSIONS:
        return False
    return len(path.split('/')) >= 2

def _walk_json_ld(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json_ld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json_ld(child)

def _parse_json_ld(soup):
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        for obj in _walk_json_ld(data):
            obj_type = obj.get('@type')
            if isinstance(obj_type, list):
                is_product = 'Product' in obj_type
            else:
                is_product = obj_type == 'Product'
            if is_product:
                products.append(obj)
    return products

def _image_from_product(data):
    image = data.get('image') if isinstance(data, dict) else None
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get('url') or image.get('contentUrl')
    if not image:
        return None
    return str(image)

def _selected_size(soup, data, h1_name):
    """Extract the actually selected bottle size."""
    visible_sources = [h1_name, clean(data.get('name')) if isinstance(data, dict) else '']
    for value in visible_sources:
        match = re.search('(?<!\\d)(\\d{1,4})\\s*ml\\b', value, re.I)
        if match:
            return int(match.group(1))
    selectors = ['input[type="radio"][checked]', 'input[type="radio"][aria-checked="true"]', 'input[checked][name*="size" i]', 'option[selected]', '[aria-selected="true"]']
    for selector in selectors:
        for node in soup.select(selector):
            chunks = [node.get('value', ''), node.get('aria-label', ''), node.get('data-value', ''), node.get('data-size', ''), node.get_text(' ', strip=True)]
            parent = node.parent
            if parent:
                chunks.append(parent.get_text(' ', strip=True))
            grand = parent.parent if parent else None
            if grand:
                chunks.append(grand.get_text(' ', strip=True))
            blob = ' '.join(chunks)
            match = re.search('(?<!\\d)(\\d{1,4})\\s*ml\\b', blob, re.I)
            if match:
                return int(match.group(1))
    return size_ml(h1_name, data.get('name') if isinstance(data, dict) else '')

def _product(url, html, query):
    soup = BeautifulSoup(html, 'html.parser')
    jsonld_products = _parse_json_ld(soup)
    data = jsonld_products[0] if jsonld_products else {}
    h1 = soup.find('h1')
    h1_name = clean(h1.get_text(' ', strip=True)) if h1 else ''
    name = h1_name or clean(data.get('name'))
    if not name or not matches(name, query):
        for candidate in jsonld_products:
            candidate_name = clean(candidate.get('name'))
            if candidate_name and matches(candidate_name, query):
                data = candidate
                name = candidate_name
                break
    if not name or not matches(name, query):
        return None
    text = soup.get_text(' ', strip=True)
    brand = data.get('brand')
    if isinstance(brand, dict):
        brand = brand.get('name')
    offers = data.get('offers')
    if isinstance(offers, list):
        offer_list = [x for x in offers if isinstance(x, dict)]
    elif isinstance(offers, dict):
        offer_list = [offers]
    else:
        offer_list = []
    offer = next((x for x in offer_list if x.get('price') is not None), {})
    price = parse_price(offer.get('price'))
    if price is None:
        prices = _extract_prices(text)
        if prices:
            price = parse_price(prices[0])
    if price is None:
        return None
    gtin = clean(data.get('gtin13') or data.get('gtin') or '') or None
    mpn = clean(data.get('mpn') or '') or None
    sku = clean(data.get('sku') or '') or None
    image = _image_from_product(data)
    if image:
        image = urljoin(url, image)
    availability = availability_from_sources(data, soup)
    selected_size = _selected_size(soup, data, h1_name)
    return {'store': STORE, 'source': {'source_name': name, 'source_brand': clean(brand), 'url': url, 'image': image}, 'identity': {'gtin': {'value': gtin, 'source': 'jsonld'} if gtin else None, 'mpn': {'value': mpn, 'source': 'jsonld'} if mpn else None, 'sku': {'value': sku, 'source': 'jsonld'} if sku else None, 'store_product_id': {'value': sku, 'source': 'notino_sku'} if sku else None}, 'attributes': {'size_ml': {'value': selected_size, 'source': 'selected_variant_or_product_name'} if selected_size is not None else None, 'concentration': {'value': concentration(name), 'source': 'product_name'} if concentration(name) else None, 'gender': {'value': 'unknown', 'source': 'not_explicit'}, 'packaging_type': {'value': 'product', 'source': 'default'}}, 'offer': {'price': price, 'currency': 'EUR', 'availability': availability}, 'provenance': {'source_page': url, 'product_source': 'jsonld_or_page'}, 'raw_data': {'jsonld': data}, 'name': name, 'price': f'{price:.2f}'.replace('.', ',') + ' €', 'url': url, 'available': availability == 'in_stock'}

def _search_pages(query):
    return (SEARCH_URL.format(query=quote_plus(query)),)

def _discover_with_playwright(query, max_urls=80):
    if sync_playwright is None:
        return []
    urls = []
    seen = set()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
            context = browser.new_context(user_agent=HEADERS['User-Agent'], locale='fr-FR', extra_http_headers={'Accept-Language': HEADERS['Accept-Language']}, viewport={'width': 1365, 'height': 900})
            page = context.new_page()
            for url in _search_pages(query):
                try:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=DEFAULT_TIMEOUT_MS)
                except Exception:
                    continue
                if response is not None and response.status >= 400:
                    continue
                try:
                    page.wait_for_load_state('networkidle', timeout=min(DEFAULT_TIMEOUT_MS, 15000))
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(1200)
                try:
                    page.evaluate('\n                        () => {\n                            window.scrollTo(\n                                0,\n                                document.body.scrollHeight\n                            );\n                        }\n                        ')
                    page.wait_for_timeout(800)
                except Exception:
                    pass
                html = page.content()
                for product_url in _candidate_product_urls(html, query):
                    if product_url in seen:
                        continue
                    seen.add(product_url)
                    urls.append(product_url)
                    if len(urls) >= max_urls:
                        browser.close()
                        return urls[:max_urls]
            browser.close()
    except Exception as exc:
        LOGGER.warning('Notino Playwright discovery error: %s', exc)
    return urls[:max_urls]

def _discover_from_search_requests(session, query, max_urls=80):
    urls = []
    seen = set()
    landing_pages = []
    landing_seen = set()

    def add(values):
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            urls.append(value)
            if len(urls) >= max_urls:
                return True
        return False

    for search_url in _search_pages(query):
        try:
            response = session.get(search_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue

        discovered = _candidate_product_urls(response.text, query)
        if add(discovered):
            return urls[:max_urls]

        # If search results expose a query-matching collection/landing page
        # instead of direct product cards, keep it for one controlled second
        # stage. The product page itself will still be validated by _product().
        soup = BeautifulSoup(response.text, 'html.parser')
        for node in soup.find_all(True):
            for attr in ('href', 'data-href', 'data-url', 'data-product-url'):
                raw = node.get(attr)
                if not raw:
                    continue
                raw = clean(str(raw))
                if raw.startswith('/'):
                    raw = urljoin(BASE_URL, raw)
                candidate = _normalise_url(raw)
                if not candidate or candidate in landing_seen:
                    continue
                if not matches(urlparse(candidate).path.replace('-', ' '), query):
                    continue
                landing_seen.add(candidate)
                landing_pages.append(candidate)
                if len(landing_pages) >= 8:
                    break
            if len(landing_pages) >= 8:
                break

    for landing_url in landing_pages:
        try:
            response = session.get(landing_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue
        if add(_candidate_product_urls(response.text, query)):
            return urls[:max_urls]

    return urls[:max_urls]

def _candidate_product_urls(html, query):
    """Discover Notino FR product pages from every useful search-page representation."""
    soup = BeautifulSoup(html, 'html.parser')
    found, seen = ([], set())
    query_norm = norm(query)

    def add(raw_url, context=''):
        if not raw_url:
            return
        raw_url = clean(str(raw_url)).replace('\\/', '/').replace('\\u002F', '/')
        if raw_url.startswith('//'):
            raw_url = 'https:' + raw_url
        elif raw_url.startswith('/'):
            raw_url = urljoin(BASE_URL, raw_url)
        url = _normalise_url(raw_url)
        if not url or not _looks_like_product_url(url) or url in seen:
            return
        slug_text = urlparse(url).path.replace('-', ' ')
        combined = f'{context} {slug_text}'
        # Search-page markup is not stable: the product title and URL are
        # sometimes rendered in different DOM nodes. Do not discard a valid
        # Notino product URL merely because the query text is absent from the
        # local node context. The product page is validated later by _product.
        if not matches(combined, query) and query_norm not in norm(combined):
            if '/p-' not in urlparse(url).path.lower():
                return
        seen.add(url)
        found.append(url)

    canonical = soup.select_one('link[rel="canonical"]')
    if canonical and canonical.get('href'):
        add(canonical.get('href'), query)

    attrs = ('href', 'data-href', 'data-url', 'data-product-url', 'content')
    for node in soup.find_all(True):
        context = node.get_text(' ', strip=True)
        for attr in attrs:
            add(node.get(attr), context)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        for obj in _walk_json_ld(data):
            if not isinstance(obj, dict):
                continue
            name = clean(obj.get('name', ''))
            for key in ('url', '@id'):
                value = obj.get(key)
                if isinstance(value, str):
                    add(value, name)
            item = obj.get('item')
            if isinstance(item, dict):
                item_name = clean(item.get('name', ''))
                for key in ('url', '@id'):
                    value = item.get(key)
                    if isinstance(value, str):
                        add(value, item_name)

    decoded = html.replace('\\/', '/').replace('\\u002F', '/')
    patterns = [
        r'(?:https?:)?//(?:www\.)?notino\.fr/[^"\'<>\s\\]+',
        r'["\'](/[^"\'<>\s\\]*?/p-\d+/?[^"\'<>\s\\]*)["\']',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, decoded, re.I):
            add(raw)

    # Notino can render the search cards with the product title and URL in
    # separate JSON/HTML fragments. Collect every canonical /p-<id>/ URL and
    # let _product perform the final query validation on the actual page.
    product_id_patterns = [
        r'(?:https?:)?//(?:www\.)?notino\.fr/[^\"\'<>\s\\]+/p-\d+/?',
        r'(?P<path>/[^\"\'<>\s\\]+/p-\d+/?)',
    ]
    for pattern in product_id_patterns:
        for raw in re.findall(pattern, decoded, re.I):
            if isinstance(raw, tuple):
                raw = raw[0]
            add(raw)

    return found

def _discover(session, query):
    urls, seen = ([], set())

    def add(values):
        for url in values:
            if url not in seen:
                seen.add(url)
                urls.append(url)
        return len(urls) >= 80
    if BROWSER_ENABLED and add(_discover_with_playwright(query, 80)):
        return urls[:80]
    add(_discover_from_search_requests(session, query, 80))
    return urls[:80]

def _fetch_product_with_playwright(url):
    if sync_playwright is None or not BROWSER_ENABLED:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
            context = browser.new_context(user_agent=HEADERS['User-Agent'], locale='fr-FR', extra_http_headers={'Accept-Language': HEADERS['Accept-Language']})
            page = context.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=DEFAULT_TIMEOUT_MS)
            if response is not None and response.status >= 400:
                browser.close()
                return None
            try:
                page.wait_for_load_state('networkidle', timeout=12000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(800)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        LOGGER.warning('Notino browser product retrieval failed: %s', exc)
        return None

def search(query):
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    results, seen = ([], set())
    try:
        for url in _discover(session, query):
            html = None
            try:
                response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                if response.status_code < 400:
                    html = response.text
            except requests.RequestException:
                pass
            if not html:
                html = _fetch_product_with_playwright(url)
            if not html:
                continue
            item = _product(url, html, query)
            if not item:
                continue
            sku = item['identity'].get('sku')
            sku_value = sku.get('value') if sku else None
            key = (url, sku_value)
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
        return results
    finally:
        session.close()

def scrape(query):
    return search(query)

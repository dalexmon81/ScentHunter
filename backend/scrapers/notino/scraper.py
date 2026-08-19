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
PRODUCT_URL_RE = re.compile(r'/[^?#\s]*/p-\d+/?(?:$|[?#])', re.I)
PRODUCT_PATH_EXCLUSIONS = {'search.asp', 'parfums', 'parfums-homme', 'parfums-femme', 'cosmetiques', 'maquillage', 'cheveux', 'corps', 'visage', 'promotions', 'nouveaux', 'marques', 'panier', 'checkout', 'login', 'account', 'magazine', 'contact'}
OUT_OF_STOCK_TERMS = ('rupture de stock', 'en rupture', 'indisponible', 'épuisé', 'epuise', 'out of stock', 'sold out', 'unavailable')
IN_STOCK_TERMS = ('en stock', 'disponible', 'available', 'in stock')

def clean(value):
    return re.sub('\\s+', ' ', str(value or '')).strip()

def norm(value):
    return re.sub('\\s+', ' ', re.sub('[^a-z0-9]+', ' ', clean(value).lower())).strip()

def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}

def _gender_group(value):
    value = norm(value)
    if re.search(r'\b(him|his|man|men|male|homme|masculine|pour homme|pour men)\b', value):
        return 'men'
    if re.search(r'\b(her|woman|women|female|femme|feminine|pour femme|pour women)\b', value):
        return 'women'
    if re.search(r'\b(unisex|unisexe|mixte)\b', value):
        return 'unisex'
    return None


GENERIC_IDENTITY_WORDS = {
    'eau', 'de', 'parfum', 'perfume', 'edp', 'edt', 'extrait',
    'spray', 'for', 'by', 'pour',
    # Gender is validated separately by _gender_group().
    'him', 'his', 'man', 'men', 'male', 'homme', 'masculine',
    'her', 'woman', 'women', 'female', 'femme', 'feminine',
    'unisex', 'unisexe', 'mixte',
}


def _meaningful_tokens(value):
    return {
        token for token in tokens(value)
        if token not in GENERIC_IDENTITY_WORDS
    }


def matches(text, query):
    """Generic product identity matching.

    Discovery/search phrases often contain linguistic glue such as
    'for', 'him', 'pour' or 'homme'. Those words must not be required
    literally, but an explicitly requested gender must remain compatible
    with the product identity.
    """
    query_meaningful = _meaningful_tokens(query)
    product_tokens = tokens(text)

    if not query_meaningful:
        return False

    if not query_meaningful.issubset(product_tokens):
        return False

    requested_gender = _gender_group(query)
    if requested_gender:
        product_gender = _gender_group(text)
        if product_gender == 'women' and requested_gender == 'men':
            return False
        if product_gender == 'men' and requested_gender == 'women':
            return False

    return True


def _discovery_tokens(value):
    return _meaningful_tokens(value)


def _discovery_matches(text, query):
    query_tokens = _discovery_tokens(query)
    context_tokens = _discovery_tokens(text)
    if not query_tokens or not query_tokens.issubset(context_tokens):
        return False

    requested_gender = _gender_group(query)
    if requested_gender:
        context_gender = _gender_group(text)
        if context_gender == 'women' and requested_gender == 'men':
            return False
        if context_gender == 'men' and requested_gender == 'women':
            return False

    return True

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

def _looks_like_product_url(url, context='', query=''):
    """Recognize genuine Notino product-looking URLs.

    Discovery deliberately does not require a complete query match. Search
    pages can name the same product differently from its canonical URL and
    can express gender/concentration in localized wording. The final
    _product() validation is authoritative.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    path = parsed.path.rstrip('/')
    lower_path = path.lower()

    if not path or 'search.asp' in lower_path:
        return False

    parts = [p for p in path.split('/') if p]

    if PRODUCT_URL_RE.search(path):
        return True

    if len(parts) < 2:
        return False

    if parts[0].lower() in PRODUCT_PATH_EXCLUSIONS:
        return False

    slug = parts[-1].replace('-', ' ')
    return len(tokens(slug)) >= 2

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
    product_identity_text = ' '.join(
        value for value in (
            name,
            clean(data.get('brand')) if isinstance(data, dict) and not isinstance(data.get('brand'), dict) else '',
            urlparse(url).path.replace('/', ' ').replace('-', ' '),
        ) if value
    )

    if not name or not matches(product_identity_text, query):
        for candidate in jsonld_products:
            candidate_name = clean(candidate.get('name'))
            candidate_brand = candidate.get('brand')
            if isinstance(candidate_brand, dict):
                candidate_brand = candidate_brand.get('name')
            candidate_identity = ' '.join(
                value for value in (
                    candidate_name,
                    clean(candidate_brand),
                    urlparse(url).path.replace('/', ' ').replace('-', ' '),
                ) if value
            )
            if candidate_name and matches(candidate_identity, query):
                data = candidate
                name = candidate_name
                break

    if not name:
        return None

    final_identity = ' '.join(
        value for value in (
            name,
            clean(data.get('brand')) if isinstance(data, dict) and not isinstance(data.get('brand'), dict) else '',
            urlparse(url).path.replace('/', ' ').replace('-', ' '),
        ) if value
    )
    if not matches(final_identity, query):
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
    offer = next(
        (
            x for x in offer_list
            if x.get('price') is not None
            or x.get('lowPrice') is not None
            or x.get('highPrice') is not None
        ),
        {},
    )
    price_value = offer.get('price')
    if price_value is None:
        price_value = offer.get('lowPrice')
    if price_value is None:
        price_value = offer.get('highPrice')
    price = parse_price(price_value)
    if price is None:
        prices = _extract_prices(text)
        if prices:
            price = parse_price(prices[0])
    gtin = clean(data.get('gtin13') or data.get('gtin') or '') or None
    mpn = clean(data.get('mpn') or '') or None
    sku = clean(data.get('sku') or '') or None
    image = _image_from_product(data)
    if not image:
        meta_image = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
        if meta_image and meta_image.get('content'):
            image = clean(meta_image.get('content'))
    if image:
        image = urljoin(url, image)
    availability = availability_from_sources(data, soup)
    selected_size = _selected_size(soup, data, h1_name)
    product_url = _normalise_url(url) or url
    return {'store': STORE, 'source': {'source_name': name, 'source_brand': clean(brand), 'url': product_url, 'image': image}, 'identity': {'gtin': {'value': gtin, 'source': 'jsonld'} if gtin else None, 'mpn': {'value': mpn, 'source': 'jsonld'} if mpn else None, 'sku': {'value': sku, 'source': 'jsonld'} if sku else None, 'store_product_id': {'value': sku, 'source': 'notino_sku'} if sku else None}, 'attributes': {'size_ml': {'value': selected_size, 'source': 'selected_variant_or_product_name'} if selected_size is not None else None, 'concentration': {'value': concentration(name), 'source': 'product_name'} if concentration(name) else None, 'gender': {'value': 'unknown', 'source': 'not_explicit'}, 'packaging_type': {'value': 'product', 'source': 'default'}}, 'offer': {'price': price, 'currency': 'EUR', 'availability': availability}, 'provenance': {'source_page': product_url, 'product_source': 'jsonld_or_page'}, 'raw_data': {'jsonld': data}, 'name': name, 'price': f'{price:.2f}'.replace('.', ',') + ' €' if price is not None else '', 'url': product_url, 'available': availability == 'in_stock'}

def _search_pages(query):
    return (SEARCH_URL.format(query=quote_plus(query)),)

def _candidate_product_urls(html, query):
    """Discover and rank product candidates from Notino search HTML.

    Discovery is intentionally broad. It collects structurally plausible
    product URLs first, then ranks them using the query and local card text.
    Identity validation happens later on the actual product page.
    """
    soup = BeautifulSoup(html, 'html.parser')
    candidates = {}
    query_tokens = _meaningful_tokens(query)
    requested_gender = _gender_group(query)

    def score(url, context=''):
        path_text = urlparse(url).path.replace('/', ' ').replace('-', ' ')
        blob = norm(' '.join((context, path_text)))
        context_tokens = tokens(blob)

        overlap = len(query_tokens & context_tokens)
        exact_meaningful = query_tokens.issubset(context_tokens)
        gender = _gender_group(blob)

        value = overlap * 10
        if exact_meaningful:
            value += 25
        if requested_gender and gender == requested_gender:
            value += 8
        elif requested_gender and gender and gender != requested_gender and gender != 'unisex':
            value -= 30

        # Prefer canonical product URLs with an explicit numeric id only
        # after relevance has been considered.
        if PRODUCT_URL_RE.search(urlparse(url).path):
            value += 2

        return value

    def add(raw_url, context=''):
        if not raw_url:
            return

        raw_url = clean(str(raw_url)).replace('\\/', '/').replace('\\u002F', '/')

        if raw_url.startswith('//'):
            raw_url = 'https:' + raw_url
        elif raw_url.startswith('/'):
            raw_url = urljoin(BASE_URL, raw_url)

        url = _normalise_url(raw_url)
        if not url or not _looks_like_product_url(url, context, query):
            return

        candidate_score = score(url, context)
        previous = candidates.get(url)
        if previous is None or candidate_score > previous[0]:
            candidates[url] = (candidate_score, clean(context))

    for anchor in soup.find_all('a', href=True):
        href = anchor.get('href')
        card = anchor
        for _ in range(4):
            parent = getattr(card, 'parent', None)
            if parent is None:
                break
            card = parent
            card_text = clean(card.get_text(' ', strip=True))
            if len(card_text) >= 20:
                break

        context = ' '.join(
            value for value in (
                clean(anchor.get_text(' ', strip=True)),
                clean(card.get_text(' ', strip=True)),
                clean(anchor.get('aria-label')),
                clean(anchor.get('title')),
            ) if value
        )
        add(href, context)

    for node in soup.find_all(True):
        context = clean(node.get_text(' ', strip=True))
        for attr in ('data-href', 'data-url', 'data-product-url'):
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
            obj_name = clean(obj.get('name'))
            for key in ('url', '@id'):
                value = obj.get(key)
                if isinstance(value, str):
                    add(value, obj_name)

            item = obj.get('item')
            if isinstance(item, dict):
                item_name = clean(item.get('name'))
                for key in ('url', '@id'):
                    value = item.get(key)
                    if isinstance(value, str):
                        add(value, item_name)

    decoded = html.replace('\\/', '/').replace('\\u002F', '/')
    patterns = (
        r'(?:https?:)?//(?:www\.)?notino\.fr/[^"\'<>\s\\]+/p-\d+/?',
        r'(?P<path>/[^"\'<>\s\\]+/p-\d+/?)',
        r'(?:https?:)?//(?:www\.)?notino\.fr/(?=[^"\'<>\s\\]+/[^"\'<>\s\\]+/?(?:["\'<>\s]|$))[^"\'<>\s\\]+/[^"\'<>\s\\]+/?',
        r'(?P<canonical>/[a-z0-9][^"\'<>\s\\]*/[a-z0-9][^"\'<>\s\\]+/?)',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, decoded, re.I):
            if isinstance(raw, tuple):
                raw = raw[0]
            add(raw)

    ranked = sorted(
        candidates.items(),
        key=lambda item: (-item[1][0], len(item[0]), item[0]),
    )
    return [url for url, _meta in ranked]

def _discover_with_playwright(query, max_urls=80):
    """Browser fallback for client-rendered Notino search results."""
    if sync_playwright is None:
        return []

    urls, seen = [], set()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
            )
            context = browser.new_context(
                user_agent=HEADERS['User-Agent'],
                locale='fr-FR',
                extra_http_headers={'Accept-Language': HEADERS['Accept-Language']},
                viewport={'width': 1365, 'height': 900},
            )
            page = context.new_page()
            response = page.goto(
                _search_pages(query)[0],
                wait_until='domcontentloaded',
                timeout=DEFAULT_TIMEOUT_MS,
            )
            if response is not None and response.status >= 400:
                LOGGER.info(
                    'Notino browser search returned HTTP %s; inspecting rendered DOM anyway',
                    response.status,
                )
            try:
                page.wait_for_load_state('networkidle', timeout=min(DEFAULT_TIMEOUT_MS, 15000))
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1000)

            candidates = _candidate_product_urls(page.content(), query)

            for raw_url in candidates:
                url = _normalise_url(raw_url)
                if not url or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
                if len(urls) >= max_urls:
                    break
            browser.close()
    except Exception as exc:
        LOGGER.warning('Notino Playwright discovery error: %s', exc)

    return urls[:max_urls]

def _discover_from_search_requests(session, query, max_urls=80):
    """Discover only from Notino's own search endpoint, like Deloox."""
    try:
        response = session.get(
            _search_pages(query)[0],
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    return _candidate_product_urls(response.text, query)[:max_urls]

def _discover(session, query):
    """Combine HTTP and browser discovery without letting one source hide the other."""
    found = []
    seen = set()

    def merge(urls):
        for url in urls or []:
            normalised = _normalise_url(url)
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            found.append(normalised)
            if len(found) >= 80:
                return True
        return False

    # HTTP discovery is the fast first source.
    if merge(_discover_from_search_requests(session, query, 80)):
        return found[:80]

    # Browser discovery is also a valid generic source. It is no longer
    # skipped merely because HTTP returned some candidates: the two sources
    # can expose different parts of Notino's search result.
    if BROWSER_ENABLED:
        merge(_discover_with_playwright(query, 80))

    return found[:80]

def _fetch_product_with_playwright(url):
    if sync_playwright is None or not BROWSER_ENABLED:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
            context = browser.new_context(user_agent=HEADERS['User-Agent'], locale='fr-FR', extra_http_headers={'Accept-Language': HEADERS['Accept-Language']})
            page = context.new_page()
            response = page.goto(
                url,
                wait_until='domcontentloaded',
                timeout=DEFAULT_TIMEOUT_MS,
            )
            if response is not None and response.status >= 400:
                LOGGER.info(
                    'Notino browser product returned HTTP %s; inspecting rendered DOM anyway',
                    response.status,
                )

            # The product page can render its title/data after the initial
            # DOM load. A short fixed delay is not reliable across products.
            # Wait for a real product marker, with a bounded timeout, without
            # waiting for networkidle (Notino background requests can remain
            # open indefinitely or trigger a challenge).
            try:
                page.wait_for_selector(
                    'h1, script[type="application/ld+json"]',
                    timeout=min(DEFAULT_TIMEOUT_MS, 8000),
                    state='attached',
                )
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(800)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        LOGGER.warning('Notino browser product retrieval failed: %s', exc)
        return None


def _diagnostic_raw_links(html):
    """Extract same-site links without query matching or product filtering."""
    soup = BeautifulSoup(html, 'html.parser')
    all_links=[]
    seen=set()
    for a in soup.find_all('a', href=True):
        href=a.get('href')
        url=_normalise_url(href)
        if not url or url in seen:
            continue
        seen.add(url)
        all_links.append({
            'url': url,
            'anchor_text': clean(a.get_text(' ', strip=True)),
            'title': clean(a.get('title')),
            'aria_label': clean(a.get('aria-label')),
        })
    return all_links


def _diagnostic_productish(link):
    url=link.get('url') or ''
    path=urlparse(url).path.lower()
    if PRODUCT_URL_RE.search(path):
        return True
    parts=[p for p in path.split('/') if p]
    if len(parts)<2:
        return False
    if parts[0] in PRODUCT_PATH_EXCLUSIONS:
        return False
    return len(tokens(parts[-1].replace('-', ' '))) >= 2


def _diagnostic_playwright(query):
    """Open the search page in a real browser and return raw link evidence."""
    report={
        'attempted': False,
        'status': None,
        'final_url': None,
        'html_bytes': 0,
        'raw_link_count': 0,
        'productish_link_count': 0,
        'productish_links': [],
        'error': None,
    }
    if sync_playwright is None:
        report['error']='playwright_not_installed'
        return report

    report['attempted']=True
    browser=None
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(
                headless=True,
                args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'],
            )
            context=browser.new_context(
                user_agent=HEADERS['User-Agent'],
                locale='fr-FR',
                extra_http_headers={'Accept-Language': HEADERS['Accept-Language']},
                viewport={'width':1365,'height':900},
            )
            page=context.new_page()
            response=page.goto(
                _search_pages(query)[0],
                wait_until='domcontentloaded',
                timeout=min(DEFAULT_TIMEOUT_MS, 30000),
            )
            report['status']=response.status if response is not None else None
            report['final_url']=page.url
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1000)
            html=page.content()
            report['html_bytes']=len(html.encode('utf-8'))
            links=_diagnostic_raw_links(html)
            report['raw_link_count']=len(links)
            productish=[x for x in links if _diagnostic_productish(x)]
            report['productish_link_count']=len(productish)
            report['productish_links']=productish[:30]
    except Exception as exc:
        report['error']=type(exc).__name__ + ': ' + str(exc)
    finally:
        if browser is not None:
            try: browser.close()
            except Exception: pass
    return report


def diagnose(query):
    """Compare requests and Playwright without changing production search()."""
    query=clean(query)
    report={
        'query': query,
        'search_url': _search_pages(query)[0] if query else '',
        'http': {},
        'http_discovery': {},
        'playwright_discovery': {},
        'product_pages': [],
        'final_results': [],
    }
    if not query:
        report['http']['error']='empty_query'
        return report

    session=requests.Session()
    try:
        try:
            r=session.get(
                report['search_url'],
                headers=HEADERS,
                timeout=min(TIMEOUT, 10),
                allow_redirects=True,
            )
            body=r.text or ''
            report['http']={
                'status':r.status_code,
                'final_url':r.url,
                'elapsed_ms':round(r.elapsed.total_seconds()*1000,2),
                'html_bytes':len(body.encode('utf-8')),
                'title': clean(BeautifulSoup(body,'html.parser').title.get_text(' ',strip=True)) if BeautifulSoup(body,'html.parser').title else '',
                'body_preview':clean(BeautifulSoup(body,'html.parser').get_text(' ',strip=True))[:300],
            }
            if r.status_code < 400:
                raw=_diagnostic_raw_links(body)
                productish=[x for x in raw if _diagnostic_productish(x)]
                accepted=[]; rejected=[]
                for item in productish:
                    if _looks_like_product_url(item['url'], item.get('anchor_text',''), query):
                        accepted.append(item)
                    else:
                        rejected.append(item)
                report['http_discovery']={
                    'raw_links_seen':len(raw),
                    'productish_links':productish[:30],
                    'accepted_candidates':accepted[:30],
                    'rejected_candidates':rejected[:30],
                    'total_candidates':len(productish),
                }
            else:
                report['http_discovery']={
                    'raw_links_seen':0,
                    'productish_links':[],
                    'accepted_candidates':[],
                    'rejected_candidates':[],
                    'total_candidates':0,
                }
        except requests.RequestException as exc:
            report['http']={'status':None,'error':type(exc).__name__+': '+str(exc)}
            report['http_discovery']={'total_candidates':0}

        report['playwright_discovery']=_diagnostic_playwright(query)

        # Combine raw product-like links from Playwright, then inspect at most 5.
        candidates=[]
        seen=set()
        for item in report['playwright_discovery'].get('productish_links',[]):
            url=item.get('url')
            if not url or url in seen: continue
            seen.add(url); candidates.append(url)
        for item in report.get('http_discovery',{}).get('accepted_candidates',[]):
            url=item.get('url')
            if not url or url in seen: continue
            seen.add(url); candidates.append(url)

        for url in candidates[:5]:
            entry={'url':url,'status':None,'final_url':None,'html_bytes':0,'h1':'','jsonld_names':[],'query_matches':[],'decision':'rejected','reason':''}
            try:
                rr=session.get(url,headers=HEADERS,timeout=min(TIMEOUT,8),allow_redirects=True)
                entry['status']=rr.status_code; entry['final_url']=rr.url; entry['html_bytes']=len((rr.text or '').encode('utf-8'))
                html=rr.text if rr.status_code < 400 else None
                if not html and BROWSER_ENABLED:
                    html=_fetch_product_with_playwright(url)
                if not html:
                    entry['reason']='product_page_unavailable'
                    report['product_pages'].append(entry); continue
                soup=BeautifulSoup(html,'html.parser')
                h1=soup.find('h1')
                entry['h1']=clean(h1.get_text(' ',strip=True)) if h1 else ''
                data_list=_parse_json_ld(soup)
                entry['jsonld_names']=[clean(x.get('name')) for x in data_list if clean(x.get('name'))]
                checks=[]
                candidates_data=[]
                if entry['h1']:
                    candidates_data.append((entry['h1'],data_list[0] if data_list else {}))
                for obj in data_list:
                    name=clean(obj.get('name'))
                    if name: candidates_data.append((name,obj))
                for name,obj in candidates_data:
                    brand=obj.get('brand') if isinstance(obj,dict) else ''
                    if isinstance(brand,dict): brand=brand.get('name')
                    brand=clean(brand)
                    checks.append({'name':name,'brand':brand,'match':matches(f'{name} {brand}',query)})
                entry['query_matches']=checks
                if any(x['match'] for x in checks):
                    entry['decision']='accepted'; entry['reason']='product_identity_match'
                else:
                    entry['reason']='no_product_identity_match'
            except requests.RequestException as exc:
                entry['reason']='product_request_error: '+type(exc).__name__+': '+str(exc)
            except Exception as exc:
                entry['reason']='product_parse_error: '+type(exc).__name__+': '+str(exc)
            report['product_pages'].append(entry)

        report['final_results']=[x for x in report['product_pages'] if x.get('decision')=='accepted']
        return report
    finally:
        session.close()


def diagnostic_json(query):
    return json.dumps(diagnose(query), ensure_ascii=False, indent=2, default=str)

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
            key = (item['url'].lower(), sku_value)
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
        return results
    finally:
        session.close()

def scrape(query):
    return search(query)

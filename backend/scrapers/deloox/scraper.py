import re import time from urllib.parse import urljoin

import requests from bs4 import BeautifulSoup

STORE = “Deloox” BASE_URL = “https://www.deloox.com” HOME_URL =
BASE_URL + “/en”

HEADERS = { “User-Agent”: ( “Mozilla/5.0 (Windows NT 10.0; Win64; x64)”
“AppleWebKit/537.36 (KHTML, like Gecko)” “Chrome/131.0 Safari/537.36” ),
“Accept”:
“text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,/;q=0.8”,
“Accept-Language”: “en-GB,en;q=0.9”, “Cache-Control”: “no-cache”, }

TIMEOUT = 12 MAX_CATEGORY_PAGES = 35

PRICE_RE = re.compile( r”(?:from)?€()?()“, re.I, )

SOLD_OUT_PATTERNS = ( “sold out”, “out of stock”, “temporarily
unavailable”, “not available”, )

def _clean(value): return re.sub(r”+“,” “, str(value or”“)).strip()

def _tokens(value): return [ token for token in re.findall(r”[a-z0-9]+“,
_clean(value).lower()) if len(token) > 1 ]

def _matches(text, query): text_tokens = _tokens(text) query_tokens =
_tokens(query)

    if not query_tokens:
        return False

    return all(token in text_tokens for token in query_tokens)

def _price(text): text = _clean(text) matches =
list(PRICE_RE.finditer(text))

    if not matches:
        return None

    match = matches[-1]
    return f"{match.group(1)},{match.group(2)}€"

def _get(session, url): try: response = session.get( url,
timeout=TIMEOUT, allow_redirects=True, )

        if response.status_code != 200:
            return None

        return response

    except requests.RequestException:
        return None

def _product_links(soup): links = [] seen = set()

    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))

        if not href:
            continue

        url = urljoin(BASE_URL, href).split("?")[0]

        if "/product/" not in url.lower():
            continue

        if url in seen:
            continue

        seen.add(url)
        links.append(url)

    return links

def _extract_product_page(session, url, query): response = _get(session,
url)

    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    name = _clean(h1.get_text(" ", strip=True)) if h1 else ""

    if not name:
        return None

    page_text = _clean(soup.get_text(" ", strip=True))

    # Il match viene fatto soprattutto sul vero H1.
    # In seconda battuta usiamo il testo pagina per brand/product line.
    if not _matches(name, query) and not _matches(page_text, query):
        return None

    lower_text = page_text.lower()
    sold_out = any(x in lower_text for x in SOLD_OUT_PATTERNS)

    price = _price(page_text)

    # Un prodotto esaurito senza prezzo non deve diventare
    # un'offerta acquistabile in ScentHunter.
    if sold_out:
        return None

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": response.url.split("?")[0],
        "available": True,
        "availability": "in_stock",
    }

def _extract_cards(soup, query): ““” Estrae direttamente i prodotti
dalle card categoria quando nome + query + prezzo sono presenti nello
stesso blocco. ““” results = [] seen = set()

    for a in soup.find_all("a", href=True):
        href = _clean(a.get("href"))

        if "/product/" not in href.lower():
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if product_url in seen:
            continue

        node = a
        card = None

        for _ in range(8):
            if node is None:
                break

            text = _clean(node.get_text(" ", strip=True))

            if _matches(text, query) and _price(text):
                card = node
                break

            node = node.parent

        if card is None:
            continue

        text = _clean(card.get_text(" ", strip=True))
        lower_text = text.lower()

        if any(x in lower_text for x in SOLD_OUT_PATTERNS):
            continue

        price = _price(text)

        if not price:
            continue

        name = ""

        for selector in (
            "h1",
            "h2",
            "h3",
            "h4",
            "[class*='product-name']",
            "[class*='product-title']",
            "[itemprop='name']",
        ):
            element = card.select_one(selector)

            if not element:
                continue

            candidate = _clean(element.get_text(" ", strip=True))

            if candidate and _matches(candidate, query):
                name = candidate
                break

        if not name:
            candidate = _clean(
                a.get("title")
                or a.get("aria-label")
                or a.get_text(" ", strip=True)
            )

            if candidate and _matches(candidate, query):
                name = candidate

        if not name:
            continue

        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results

def _find_catalog_categories(session, query): ““” Deloox non espone una
normale /search?q=…: partiamo dalla home reale e ricaviamo dinamicamente
i link di brand/categorie presenti nel catalogo. ““” response =
_get(session, HOME_URL)

    if response is None:
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    exact = []
    fragrance_roots = []
    seen = set()

    for a in soup.find_all("a", href=True):
        text = _clean(a.get_text(" ", strip=True))
        href = _clean(a.get("href"))

        if not href:
            continue

        url = urljoin(BASE_URL, href)

        if "/category/" not in url.lower():
            continue

        key = url.split("?")[0]

        if key in seen:
            continue

        seen.add(key)

        if text and _matches(text, query):
            exact.append(key)

        low_text = text.lower()

        if (
            "all men's fragrances" in low_text
            or "all women" in low_text and "fragrance" in low_text
            or "all unisex fragrances" in low_text
            or low_text == "men's fragrances"
            or low_text == "women's fragrances"
            or low_text == "unisex fragrances"
        ):
            fragrance_roots.append(key)

    # Prima brand/categorie che corrispondono direttamente alla query.
    # Poi i tre cataloghi generali dei profumi.
    ordered = []

    for url in exact + fragrance_roots:
        if url not in ordered:
            ordered.append(url)

    return ordered

def _crawl_category(session, category_url, query): results = []
seen_results = set() seen_products = set()

    for page in range(1, MAX_CATEGORY_PAGES + 1):
        separator = "&" if "?" in category_url else "?"
        url = category_url if page == 1 else f"{category_url}{separator}page={page}"

        response = _get(session, url)

        if response is None:
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # 1) Tentativo veloce: estrazione direttamente dalle card.
        card_results = _extract_cards(soup, query)

        for item in card_results:
            key = item["url"]

            if key not in seen_results:
                seen_results.add(key)
                results.append(item)

        if len(results) >= 10:
            return results[:10]

        # 2) Recuperiamo i veri /product/ della pagina.
        product_urls = _product_links(soup)

        new_urls = [
            u for u in product_urls
            if u not in seen_products
        ]

        if not new_urls:
            break

        for product_url in new_urls:
            seen_products.add(product_url)

            # Prima filtriamo con il testo/link presente nella categoria
            # quando possibile, poi confermiamo sulla pagina prodotto.
            item = _extract_product_page(
                session,
                product_url,
                query,
            )

            if not item:
                continue

            key = item["url"]

            if key in seen_results:
                continue

            seen_results.add(key)
            results.append(item)

            if len(results) >= 10:
                return results[:10]

        time.sleep(0.05)

    return results

def search(query): query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    categories = _find_catalog_categories(session, query)

    if not categories:
        return []

    all_results = []
    seen = set()

    for category_url in categories:
        results = _crawl_category(
            session,
            category_url,
            query,
        )

        for item in results:
            key = item["url"]

            if key in seen:
                continue

            seen.add(key)
            all_results.append(item)

            if len(all_results) >= 10:
                return all_results[:10]

        # Se una categoria/brand specifica ha già trovato risultati,
        # non serve attraversare tutto il catalogo generale.
        if all_results and _matches(category_url, query):
            break

    return all_results[:10]

if name == “main”: print(search(“Hawas Ice”))

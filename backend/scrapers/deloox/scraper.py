import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = BASE_URL + "/en"
TIMEOUT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-GB,en;q=0.9",
}

PRICE_RE = re.compile(
    r"(?:our\s+price|from)?\s*€\s*(\d{1,4})\s*[,.\^]?\s*(\d{2})",
    re.I,
)

ML_RE = re.compile(r"\b(\d{1,4})\s*ml\b", re.I)

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _query_tokens(value):
    # I ml non fanno parte dell'identità della fragranza:
    # così una ricerca del profumo può recuperare 30/50/100 ml.
    text = ML_RE.sub(" ", str(value or ""))
    return _tokens(text)


def _matches(text, query):
    hay = _norm(text)
    words = _query_tokens(query)
    return bool(words) and all(word in hay for word in words)


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1)},{match.group(2)} €"


def _get(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response
    except requests.RequestException:
        return None


def _find_brand_category(session, query):
    response = _get(session, HOME_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    query_words = _query_tokens(query)
    candidates = []

    for link in soup.find_all("a", href=True):
        name = _clean(link.get_text(" ", strip=True))
        href = _clean(link.get("href"))

        if not name or not href:
            continue

        url = urljoin(BASE_URL, href)

        if "/category/" not in url.lower():
            continue

        brand_words = _tokens(name)
        if not brand_words:
            continue

        if all(word in query_words for word in brand_words):
            candidates.append((len(brand_words), len(name), url))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][2]


def _card_for_link(link):
    node = link
    best = link

    for _ in range(8):
        if node is None:
            break

        text = _clean(node.get_text(" ", strip=True))

        if len(text) > 2500:
            break

        best = node

        if _extract_price(text):
            return node

        node = node.parent

    return best


def _best_name(card, link, query):
    candidates = []

    for tag in card.find_all(["h1", "h2", "h3", "h4"]):
        text = _clean(tag.get_text(" ", strip=True))
        if text:
            candidates.append(text)

    for a in card.find_all("a", href=True):
        text = _clean(a.get_text(" ", strip=True))
        if text:
            candidates.append(text)

    link_text = _clean(link.get_text(" ", strip=True))
    if link_text:
        candidates.append(link_text)

    for text in candidates:
        if _matches(text, query):
            return text

    card_text = _clean(card.get_text(" ", strip=True))

    if _matches(card_text, query):
        ml = ML_RE.search(card_text)
        if ml:
            return f"{query} {ml.group(1)} ml"
        return query

    return ""


def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        card = _card_for_link(link)
        card_text = _clean(card.get_text(" ", strip=True))

        # Il match viene fatto sull'intera card, non solo sul testo del link.
        # Deloox può separare nome, formato e prezzo in elementi diversi.
        if not _matches(card_text, query):
            continue

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue

        price = _extract_price(card_text)
        if not price:
            continue

        name = _best_name(card, link, query)
        if not name:
            continue

        ml = ML_RE.search(card_text)
        if ml and not ML_RE.search(name):
            name = f"{name} {ml.group(1)} ml"

        # La stessa fragranza può avere URL/formati distinti.
        size = ml.group(1) if ml else ""
        key = (product_url, size)

        if key in seen:
            continue

        seen.add(key)

        results.append({
            "store": STORE,
            "name": name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results


def _extract_product_page(html, url, query):
    soup = BeautifulSoup(html, "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))

    if not _matches(page_text, query):
        return []

    if any(word in page_text.lower() for word in SOLD_OUT):
        return []

    price = None

    # Prima cerca il prezzo nei blocchi prezzo.
    for selector in (
        "[class*='price']",
        "[id*='price']",
        "[itemprop='price']",
    ):
        for element in soup.select(selector):
            price = _extract_price(_clean(element.get_text(" ", strip=True)))
            if price:
                break
        if price:
            break

    if not price:
        price = _extract_price(page_text)

    if not price:
        return []

    h1 = soup.find("h1")
    name = _clean(h1.get_text(" ", strip=True)) if h1 else query

    ml = ML_RE.search(page_text)
    if ml and not ML_RE.search(name):
        name = f"{name} {ml.group(1)} ml"

    return [{
        "store": STORE,
        "name": name,
        "price": price,
        "url": url.split("?")[0],
        "available": True,
        "availability": "in_stock",
    }]


def _sitemap_product_urls(session, query):
    """
    Fallback generale: usa le sitemap pubbliche di Deloox per trovare
    pagine prodotto anche quando il brand non compare nella home.
    Non contiene profumi hardcoded.
    """
    roots = [
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
    ]

    wanted = _query_tokens(query)
    found = []
    checked_maps = set()

    def scan_map(url, depth=0):
        if depth > 2 or url in checked_maps or len(found) >= 30:
            return

        checked_maps.add(url)
        response = _get(session, url)

        if response is None:
            return

        soup = BeautifulSoup(response.text, "xml")
        locs = [_clean(x.get_text()) for x in soup.find_all("loc")]

        for loc in locs:
            low = loc.lower()

            if low.endswith(".xml") or "sitemap" in low:
                scan_map(loc, depth + 1)
                continue

            if "/product/" not in low:
                continue

            # URL slug come primo filtro; se non basta verrà controllata
            # comunque la pagina prodotto.
            slug = _norm(loc)

            if all(token in slug for token in wanted):
                if loc not in found:
                    found.append(loc)

    for root in roots:
        scan_map(root)

    return found


def _dedupe(results):
    out = []
    seen = set()

    for item in results:
        ml = ML_RE.search(item.get("name", ""))
        size = ml.group(1) if ml else ""
        key = (
            item.get("url", "").split("?")[0],
            size,
            item.get("price", ""),
        )

        if key in seen:
            continue

        seen.add(key)
        out.append(item)

    return out


def search(query):
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    results = []

    # 1) Percorso già esistente: brand -> categoria.
    brand_url = _find_brand_category(session, query)

    if brand_url:
        response = _get(session, brand_url)

        if response is not None:
            results.extend(_extract_category(response.text, query))

    # 2) Fallback: sitemap -> tutte le pagine prodotto corrispondenti.
    # Serve soprattutto quando la categoria brand non restituisce le card
    # oppure quando i formati sono pagine prodotto separate.
    if not results:
        for product_url in _sitemap_product_urls(session, query):
            response = _get(session, product_url)

            if response is None:
                continue

            results.extend(
                _extract_product_page(
                    response.text,
                    response.url,
                    query,
                )
            )

    return _dedupe(results)[:20]


if __name__ == "__main__":
    for q in (
        "Tom Ford Neroli Portofino",
        "French Avenue Liquid Brun",
        "Miu Miu Miutine",
        "Rasasi Hawas Ice",
    ):
        print("\nQUERY:", q)
        for item in search(q):
            print(item)

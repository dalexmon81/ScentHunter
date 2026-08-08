import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
TIMEOUT = 7
MAX_RESULTS = 20
MAX_JSON_PAGES = 12
MAX_HTML_PAGES = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/json,application/xhtml+xml,*/*;q=0.8",
}

EXCLUDED_WORDS = {
    "tester",
    "gift",
    "set",
    "bundle",
    "duo",
    "box",
    "discovery",
    "mini",
    "sample",
    "samples",
    "deodorant",
    "body",
    "shower",
    "lotion",
    "cream",
}


def _norm(value):
    value = str(value or "").lower()
    value = value.replace("é", "e").replace("è", "e").replace("ê", "e")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value):
    return set(_norm(value).split())


def _is_excluded(name):
    tokens = _tokens(name)
    return bool(tokens & EXCLUDED_WORDS)


def _match_score(name, query):
    name_tokens = _tokens(name)
    query_tokens = _tokens(query)

    if not query_tokens:
        return 0

    # Tutte le parole della ricerca devono essere presenti nel nome.
    if not query_tokens.issubset(name_tokens):
        return 0

    score = len(query_tokens) * 10

    # Premia il nome che contiene esattamente la sequenza cercata.
    nq = _norm(query)
    nn = _norm(name)
    if nq and nq in nn:
        score += 30

    # Penalizza leggermente prodotti accessori, senza eliminarli tutti.
    if _is_excluded(name):
        return 0

    return score


def _format_price(value):
    if value is None:
        return None

    text = str(value).strip().replace("€", "").replace(" ", "")
    text = text.replace(".", ".")

    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return None

    if number <= 0:
        return None

    return f"{number:.2f}".replace(".", ",") + " €"


def _price_from_text(text):
    if not text:
        return None

    # Bplatz mostra spesso anche il prezzo al litro/ml.
    # Quello NON deve essere restituito come prezzo del prodotto.
    patterns = [
        r"(?:retail\s+price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(?:regular\s+price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(?:price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)(?!\s*/)",
        r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)(?!\s*/)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            price = _format_price(match.group(1))
            if price:
                return price

    return None


def _product_url(handle):
    if not handle:
        return None
    handle = str(handle).strip()
    if handle.startswith("http://") or handle.startswith("https://"):
        return handle.split("#")[0].split("?")[0]
    return urljoin(BASE, "/products/" + handle).split("#")[0].split("?")[0]


def _product_from_json(product, query):
    if not isinstance(product, dict):
        return None

    title = str(product.get("title") or "").strip()
    score = _match_score(title, query)
    if not score:
        return None

    variants = product.get("variants") or []
    if isinstance(variants, dict):
        variants = [variants]

    available_variant = None
    best_variant = None

    for variant in variants:
        if not isinstance(variant, dict):
            continue

        if best_variant is None:
            best_variant = variant

        available = variant.get("available")
        if available:
            available_variant = variant
            break

    variant = available_variant or best_variant
    if not variant:
        return None

    if variant.get("available") is False:
        return None

    price = _format_price(variant.get("price"))
    if not price:
        price = _price_from_text(json.dumps(product))

    if not price:
        return None

    handle = product.get("handle")
    url = _product_url(handle)
    if not url:
        return None

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": url,
        "available": True,
        "availability": "in_stock",
        "_score": score,
    }


def _extract_products_json(data, query):
    if not isinstance(data, dict):
        return []

    products = data.get("products")
    if not isinstance(products, list):
        return []

    results = []
    seen = set()

    for product in products:
        item = _product_from_json(product, query)
        if not item:
            continue

        key = item["url"].lower()
        if key in seen:
            continue

        seen.add(key)
        results.append(item)

    return results


def _search_json(session, query):
    """Try Shopify's public product JSON/search endpoints first."""
    q = quote_plus(query)
    endpoints = [
        f"{BASE}/search/suggest.json?q={q}&resources[type]=product&resources[limit]={MAX_RESULTS}",
        f"{BASE}/search/suggest.json?q={q}&resources[type]=product&resources[limit]={MAX_RESULTS}&resources[options][unavailable_products]=hide",
        f"{BASE}/collections/all-products/products.json?limit=250&page=1",
        f"{BASE}/collections/Products-a/products.json?limit=250&page=1",
    ]

    results = []
    seen = set()

    for url in endpoints:
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code != 200 or not response.text:
            continue

        try:
            data = response.json()
        except ValueError:
            continue

        # search/suggest.json usa spesso resources.results.products.
        if "resources" in data:
            resources = data.get("resources") or {}
            results_block = resources.get("results") or {}
            products = results_block.get("products") or []
            data = {"products": products}

        page_results = _extract_products_json(data, query)

        for item in page_results:
            key = item["url"].lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

        if results:
            break

    return results


def _extract_html_cards(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = urljoin(BASE, link.get("href", ""))
        if "/products/" not in href.lower():
            continue

        href = href.split("#")[0].split("?")[0]
        card = link

        for _ in range(7):
            parent = getattr(card, "parent", None)
            if not parent:
                break

            text = " ".join(parent.stripped_strings).strip()
            if len(text) > 2200:
                break

            card = parent

            if "€" in text and (
                "wishlist" in text.lower()
                or "add to cart" in text.lower()
                or "retail price" in text.lower()
                or "show product" in text.lower()
            ):
                break

        title_candidates = [
            " ".join(link.stripped_strings).strip(),
            str(link.get("title") or "").strip(),
            str(link.get("aria-label") or "").strip(),
        ]

        image = card.find("img")
        if image:
            title_candidates.append(str(image.get("alt") or "").strip())

        title = next(
            (x for x in title_candidates if _match_score(x, query)),
            None,
        )
        if not title:
            continue

        card_text = " ".join(card.stripped_strings).strip()
        lower = card_text.lower()
        if any(x in lower for x in ("sold out", "out of stock", "not available")):
            continue

        price = _price_from_text(card_text)
        if not price:
            continue

        score = _match_score(title, query)
        key = href.lower()
        if key in seen:
            continue

        seen.add(key)
        results.append({
            "store": STORE,
            "name": title,
            "price": price,
            "url": href,
            "available": True,
            "availability": "in_stock",
            "_score": score,
        })

    return results


def _search_html(session, query):
    q = quote_plus(query)
    urls = [
        f"{BASE}/search?q={q}&type=product",
        f"{BASE}/search?q={q}",
    ]

    for url in urls:
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code != 200 or not response.text:
            continue

        results = _extract_html_cards(response.text, query)
        if results:
            return results

    return []


def _search_collection_pages(session, query):
    """General fallback: scan Bplatz's real product catalogue pages."""
    results = []
    seen = set()

    for page in range(1, MAX_HTML_PAGES + 1):
        if page == 1:
            url = f"{BASE}/collections/all-products"
        else:
            url = f"{BASE}/collections/all-products?page={page}"

        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code != 200 or not response.text:
            continue

        page_results = _extract_html_cards(response.text, query)

        for item in page_results:
            key = item["url"].lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

        # Se abbiamo già trovato risultati, non serve continuare a
        # scaricare altre pagine del catalogo.
        if results:
            break

    return results


def _verify_product_page(session, item, query):
    """Verify title, availability and actual product price on Bplatz."""
    try:
        response = session.get(
            item["url"],
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return item

    if response.status_code != 200 or not response.text:
        return item

    soup = BeautifulSoup(response.text, "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = " ".join(h1.stripped_strings).strip()

    if not title:
        meta = soup.find("meta", property="og:title")
        if meta:
            title = str(meta.get("content") or "").strip()

    if title and _match_score(title, query):
        item["name"] = title
        item["_score"] = _match_score(title, query)

    page_text = " ".join(soup.stripped_strings).strip()
    lower = page_text.lower()
    if any(x in lower for x in ("sold out", "out of stock", "not available")):
        return None

    price = _price_from_text(page_text)

    # Fallback JSON-LD.
    if not price:
        for script in soup.find_all("script", type="application/ld+json"):
            raw = script.string or script.get_text()
            try:
                data = json.loads(raw)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

            objects = data if isinstance(data, list) else [data]
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                offers = obj.get("offers") or []
                if isinstance(offers, dict):
                    offers = [offers]
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    availability = str(offer.get("availability") or "").lower()
                    if "outofstock" in availability:
                        continue
                    price = _format_price(offer.get("price"))
                    if price:
                        break
                if price:
                    break
            if price:
                break

    if price:
        item["price"] = price

    item["available"] = True
    item["availability"] = "in_stock"
    return item


def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    candidates = []
    seen = set()

    # 1. Shopify JSON: veloce e generale.
    for item in _search_json(session, query):
        key = item["url"].lower()
        if key not in seen:
            seen.add(key)
            candidates.append(item)

    # 2. Ricerca HTML Shopify.
    if not candidates:
        for item in _search_html(session, query):
            key = item["url"].lower()
            if key not in seen:
                seen.add(key)
                candidates.append(item)

    # 3. Ultimo fallback: catalogo generale Bplatz.
    if not candidates:
        for item in _search_collection_pages(session, query):
            key = item["url"].lower()
            if key not in seen:
                seen.add(key)
                candidates.append(item)

    # Verifica finale direttamente sulla pagina prodotto.
    verified = []
    for item in candidates[:MAX_RESULTS]:
        checked = _verify_product_page(session, item, query)
        if checked:
            verified.append(checked)

    # Ordine: prima il match più preciso, poi nome.
    verified.sort(
        key=lambda x: (
            -int(x.get("_score", 0)),
            len(_norm(x.get("name", ""))),
            _norm(x.get("name", "")),
        )
    )

    for item in verified:
        item.pop("_score", None)

    return verified[:MAX_RESULTS]


if __name__ == "__main__":
    for query in (
        "Liquid Brun",
        "Liquid Brun Limited Edition",
        "Rasasi Hawas",
        "Rasasi Hawas Ice",
        "Armaf Club de Nuit",
        "Afnan 9 PM",
        "French Avenue",
    ):
        print("\n" + "=" * 70)
        print("QUERY:", query)
        items = search(query)
        print("RISULTATI:", len(items))
        for item in items:
            print(item)

import json
import re
import html
from typing import List, Dict, Optional, Iterable
from urllib.parse import quote_plus, urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup


STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}


def _clean(value) -> str:
    return re.sub(
        r"\s+",
        " ",
        html.unescape(str(value or "")),
    ).strip()


def _norm(value) -> str:
    value = _clean(value).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value: str) -> List[str]:
    return [x for x in _norm(value).split() if x]


def _token_matches(query_token: str, product_token: str) -> bool:
    """
    Confronto generico dei token.

    La parte importante per Orioudh è che alcuni URL Shopify usano
    '900' mentre il nome prodotto usa '9 PM'. Non viene inserito
    nessun nome di profumo: si gestiscono genericamente i numeri
    composti dalla stessa cifra seguita da zeri.
    """
    if query_token == product_token:
        return True

    if query_token.isdigit() and product_token.isdigit():
        if (
            len(query_token) < len(product_token)
            and product_token.startswith(query_token)
            and set(product_token[len(query_token):]) == {"0"}
        ):
            return True

    return False


def _matches(text: str, query: str) -> bool:
    product_tokens = _tokens(text)
    query_tokens = _tokens(query)

    if not query_tokens:
        return False

    return all(
        any(_token_matches(q, p) for p in product_tokens)
        for q in query_tokens
    )


def _price(value) -> Optional[str]:
    if value is None:
        return None

    s = _clean(value).replace("€", "").strip()
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", s)

    if not m:
        return None

    try:
        number = float(m.group(1).replace(",", "."))
    except ValueError:
        return None

    if number <= 0:
        return None

    return f"{number:.2f}".replace(".", ",") + " €"


def _product_url(value: str) -> str:
    return urljoin(BASE_URL, str(value or "")).split("?")[0].rstrip("/")


def _canonical_path(url: str) -> str:
    return urlparse(url).path.rstrip("/").lower()


def _product_from_shopify_json(
    data: Dict,
    url: str,
    query: str,
) -> Optional[Dict[str, object]]:
    if not isinstance(data, dict):
        return None

    title = _clean(data.get("title"))
    if not title or not _matches(title, query):
        return None

    variants = data.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    # Shopify .js è la fonte primaria per lo stock reale.
    available_variants = [
        v for v in variants
        if isinstance(v, dict) and v.get("available") is True
    ]

    is_available = bool(available_variants)

    # Se è esaurito, conserviamo comunque il prezzo del prodotto.
    pool = available_variants or [
        v for v in variants if isinstance(v, dict)
    ]

    prices = []

    for variant in pool:
        value = variant.get("price")

        if value is None:
            continue

        try:
            number = float(str(value).replace(",", "."))

            # Shopify .js normalmente usa prezzi decimali.
            # Alcuni endpoint possono restituire centesimi.
            if number >= 10000:
                number /= 100

            prices.append(number)
        except (TypeError, ValueError):
            continue

    price = ""
    if prices:
        price = f"{min(prices):.2f}".replace(".", ",") + " €"

    if not price:
        price = _price(data.get("price")) or _price(data.get("price_min")) or ""

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": url,
        "available": is_available,
        "availability": "in_stock" if is_available else "out_of_stock",
        "stock_status": "in_stock" if is_available else "out_of_stock",
    }


def _fetch_product_json(
    session: requests.Session,
    url: str,
) -> Optional[Dict]:
    clean = _product_url(url)
    endpoint = clean + ".js"

    try:
        response = session.get(
            endpoint,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            return None

        data = response.json()

        return data if isinstance(data, dict) else None

    except (requests.RequestException, ValueError):
        return None


def _from_shopify_predictive(
    session: requests.Session,
    query: str,
) -> List[str]:
    endpoint = BASE_URL + "/search/suggest.json"

    params = {
        "q": query,
        "resources[type]": "product",
        "resources[options][unavailable_products]": "show",
        "resources[limit]": "20",
    }

    urls = []

    try:
        response = session.get(
            endpoint,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        products = (
            data.get("resources", {})
            .get("results", {})
            .get("products", [])
        )

        for product in products:
            if not isinstance(product, dict):
                continue

            title = _clean(product.get("title"))
            url = _product_url(product.get("url"))

            if not url or "/products/" not in url:
                continue

            if _matches(title, query):
                urls.append(url)

    except (requests.RequestException, ValueError, TypeError):
        pass

    return urls


def _from_search_html(
    session: requests.Session,
    query: str,
) -> List[str]:
    url = (
        BASE_URL
        + "/search?q="
        + quote_plus(query)
        + "&type=product"
    )

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return []

    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    urls = []

    for link in soup.select('a[href*="/products/"]'):
        href = _product_url(link.get("href"))

        if not href or "/products/" not in href:
            continue

        title = _clean(
            link.get("title")
            or link.get("aria-label")
            or link.get_text(" ", strip=True)
        )

        # Se il testo del link è troppo povero, prova il card circostante.
        candidates = [title]

        card = link
        for _ in range(5):
            if not card.parent:
                break

            card = card.parent
            candidates.append(
                _clean(card.get_text(" ", strip=True))
            )

        if any(_matches(candidate, query) for candidate in candidates):
            urls.append(href)

    return urls


def _sitemap_urls(
    session: requests.Session,
) -> Iterable[str]:
    """
    Recupera gli URL prodotto dal sitemap Shopify.

    Questo è il fallback che risolve il caso in cui il prodotto esista
    realmente nel catalogo ma Shopify non lo restituisca nella ricerca.
    """
    sitemap_candidates = [
        BASE_URL + "/sitemap_products_1.xml?from=0&to=250",
        BASE_URL + "/sitemap_products_1.xml",
        BASE_URL + "/sitemap.xml",
    ]

    seen_sitemaps = set()
    product_urls = set()

    for sitemap_url in sitemap_candidates:
        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        try:
            response = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            if response.status_code != 200:
                continue

            root = ET.fromstring(response.content)

        except (
            requests.RequestException,
            ET.ParseError,
        ):
            continue

        root_tag = root.tag.lower()

        # Sitemap prodotto diretto.
        if root_tag.endswith("urlset"):
            for loc in root.findall(
                ".//{*}loc"
            ):
                value = _clean(loc.text)

                if "/products/" in value:
                    product_urls.add(
                        _product_url(value)
                    )

            if product_urls:
                return product_urls

        # Sitemap indice: recuperiamo i sotto-sitemap.
        if root_tag.endswith("sitemapindex"):
            child_sitemaps = []

            for loc in root.findall(
                ".//{*}loc"
            ):
                value = _clean(loc.text)

                if "sitemap_products_" in value:
                    child_sitemaps.append(value)

            for child in child_sitemaps:
                try:
                    response = session.get(
                        child,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                    )

                    if response.status_code != 200:
                        continue

                    child_root = ET.fromstring(
                        response.content
                    )

                    for loc in child_root.findall(
                        ".//{*}loc"
                    ):
                        value = _clean(loc.text)

                        if "/products/" in value:
                            product_urls.add(
                                _product_url(value)
                            )

                except (
                    requests.RequestException,
                    ET.ParseError,
                ):
                    continue

            if product_urls:
                return product_urls

    return product_urls


def _url_is_candidate(
    url: str,
    query: str,
) -> bool:
    """
    Pre-filtra gli URL del sitemap senza scaricare centinaia di pagine.

    Confronta il testo dello slug con la query e permette la forma
    numerica '9' -> '900' quando il numero più lungo è lo stesso
    numero seguito solo da zeri.
    """
    slug = _norm(
        urlparse(url).path.rsplit("/", 1)[-1]
    )

    return _matches(slug, query)


def _discover_from_sitemap(
    session: requests.Session,
    query: str,
) -> List[str]:
    urls = []

    for url in _sitemap_urls(session):
        if _url_is_candidate(url, query):
            urls.append(url)

    return urls


def _build_queries(query: str) -> List[str]:
    """
    Genera poche forme generiche della query.

    Non contiene nomi di profumi.
    """
    raw = _clean(query)
    normalized = _norm(raw)

    attempts = []
    seen = set()

    def add(value: str):
        value = _clean(value)

        if not value:
            return

        key = _norm(value)

        if key and key not in seen:
            seen.add(key)
            attempts.append(value)

    add(raw)

    # Forma compatta: 9 PM -> 9PM.
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )

    add(compact)

    # Token significativi singoli come fallback Shopify.
    for token in normalized.split():
        if len(token) >= 3:
            add(token)

    return attempts[:5]


def search(query: str) -> List[Dict[str, object]]:
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()

    candidate_urls = []
    seen_urls = set()

    def add_urls(urls):
        for url in urls:
            url = _product_url(url)

            if not url or "/products/" not in url:
                continue

            key = _canonical_path(url)

            if key in seen_urls:
                continue

            seen_urls.add(key)
            candidate_urls.append(url)

    # ---------------------------------------------------------
    # 1. Ricerca Shopify standard
    # ---------------------------------------------------------
    for attempt in _build_queries(query):
        add_urls(
            _from_shopify_predictive(
                session,
                attempt,
            )
        )

        add_urls(
            _from_search_html(
                session,
                attempt,
            )
        )

    # ---------------------------------------------------------
    # 2. FALLBACK CATALOGO / SITEMAP
    # ---------------------------------------------------------
    # Se Shopify search non trova un prodotto che esiste davvero,
    # cerchiamo nel catalogo prodotto del negozio.
    if not candidate_urls:
        add_urls(
            _discover_from_sitemap(
                session,
                query,
            )
        )

    # Anche se abbiamo trovato qualcosa con la search, il sitemap
    # può contenere altri prodotti della stessa query.
    add_urls(
        _discover_from_sitemap(
            session,
            query,
        )
    )

    # ---------------------------------------------------------
    # 3. Leggiamo il JSON canonico del prodotto
    # ---------------------------------------------------------
    final = []
    seen_products = set()

    for url in candidate_urls:
        data = _fetch_product_json(
            session,
            url,
        )

        if not data:
            continue

        item = _product_from_shopify_json(
            data,
            url,
            query,
        )

        if not item:
            continue

        key = _canonical_path(
            item["url"]
        )

        if key in seen_products:
            continue

        seen_products.add(key)
        final.append(item)

    return final


if __name__ == "__main__":
    tests = (
        "9 PM",
        "9 PM Rebel",
        "9 PM Pour Femme",
        "Rayhaan Aquatica",
        "Turathi Blue",
    )

    for query in tests:
        print("\nQUERY:", query)

        for item in search(query):
            print(item)

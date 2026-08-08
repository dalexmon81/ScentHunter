import json
import re
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import quote_plus, urljoin

STORE = "Bplatz"
BASE = "https://en.bplatz.de"
TIMEOUT = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

DIRECT_PRODUCTS = (
    (
        ("liquid", "brun", "limited", "edition"),
        (
            BASE + "/Products/liquid-brun-limited-edition-eau-de-parfum-150-ml",
        ),
    ),
    (
        ("liquid", "brun"),
        (
            BASE + "/products/fragrance-world-liquid-brun-eau-de-parfum-100ml",
        ),
    ),
)


def _norm(v):
    v = str(v or "").lower()
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def _match(text, query):
    words = _norm(query).split()
    hay = _norm(text)
    return bool(words) and all(w in hay.split() for w in words)


def _price(text):
    if not text:
        return None

    # Prima cerca il prezzo reale del prodotto.
    # "Price €620 / pro l" è un prezzo al litro e NON va usato.
    patterns = [
        r"(?:regular\s+price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(?:retail\s+price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"(?:price)\s*€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
        r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)(?!\s*/)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if not m:
            continue

        value = m.group(1).replace(".", ",")

        try:
            if float(value.replace(",", ".")) <= 0:
                continue
        except ValueError:
            continue

        if "," not in value:
            value += ",00"

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

        if len(text) > 1800:
            break

        best = parent

        if "€" in text and (
            "add to" in text.lower()
            or "wishlist" in text.lower()
            or "retail price" in text.lower()
            or "regular price" in text.lower()
            or "show product" in text.lower()
        ):
            return parent

        node = parent

    return best


def _is_exact_liquid_brun(name, query):
    n = _norm(name)
    q = _norm(query)

    if not _match(n, q):
        return False

    # Non devono diventare risultati del profumo vero.
    excluded = (
        "tester",
        "gift set",
        "set",
        "bundle",
        "duo",
        "box",
        "discovery",
        "mini",
    )

    return not any(
        word in n.split()
        for word in excluded
    )


def _extract_page(html, query):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = urljoin(
            BASE,
            a.get("href", ""),
        ).split("#")[0].split("?")[0]

        if "/products/" not in href.lower():
            continue

        card = _product_card(a)
        card_text = " ".join(
            card.stripped_strings
        ).strip()

        if not _is_exact_liquid_brun(
            card_text,
            query,
        ):
            continue

        candidates = [
            " ".join(a.stripped_strings).strip(),
            (a.get("title") or "").strip(),
            (a.get("aria-label") or "").strip(),
        ]

        img = card.find("img")
        if img:
            candidates.append(
                (img.get("alt") or "").strip()
            )

        product_name = next(
            (
                x for x in candidates
                if x and _is_exact_liquid_brun(x, query)
            ),
            None,
        )

        if not product_name:
            for pa in card.find_all("a", href=True):
                txt = " ".join(
                    pa.stripped_strings
                ).strip()
                phref = urljoin(
                    BASE,
                    pa.get("href", ""),
                )

                if (
                    "/products/" in phref.lower()
                    and txt
                    and _is_exact_liquid_brun(txt, query)
                ):
                    product_name = txt
                    href = phref.split("#")[0].split("?")[0]
                    break

        if not product_name:
            continue

        if any(
            word in card_text.lower()
            for word in (
                "sold out",
                "out of stock",
                "not available",
                "available soon",
            )
        ):
            continue

        price = _price(card_text)

        if not price:
            continue

        key = href.lower()

        if key in seen:
            continue

        seen.add(key)

        out.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": href,
            "available": True,
            "availability": "in_stock",
        })

    return out


def _extract_product_page(session, url, query):
    r = session.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    if r.status_code != 200 or not r.text:
        return None

    soup = BeautifulSoup(
        r.text,
        "html.parser",
    )

    title = ""

    h1 = soup.find("h1")
    if h1:
        title = " ".join(
            h1.stripped_strings
        ).strip()

    if not title:
        meta = soup.find(
            "meta",
            property="og:title",
        )
        if meta:
            title = str(
                meta.get("content", "")
            ).strip()

    if not title or not _is_exact_liquid_brun(
        title,
        query,
    ):
        return None

    page_text = " ".join(
        soup.stripped_strings
    )

    if any(
        word in page_text.lower()
        for word in (
            "sold out",
            "out of stock",
            "not available",
            "available soon",
        )
    ):
        return None

    price = _price(page_text)

    # Shopify JSON-LD: utile quando il prezzo è separato dal testo.
    if not price:
        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):
            try:
                data = json.loads(
                    script.string or script.get_text()
                )
            except (
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ):
                continue

            objects = data if isinstance(data, list) else [data]

            for item in objects:
                if not isinstance(item, dict):
                    continue

                offers = item.get("offers", [])
                if isinstance(offers, dict):
                    offers = [offers]

                for offer in offers:
                    if not isinstance(offer, dict):
                        continue

                    availability = str(
                        offer.get(
                            "availability",
                            "",
                        )
                    ).lower()

                    if "outofstock" in availability:
                        continue

                    price_value = offer.get("price")
                    if price_value is None:
                        continue

                    price = _price(
                        f"€ {price_value}"
                    )
                    if price:
                        break

                if price:
                    break

            if price:
                break

    if not price:
        return None

    size = None
    size_match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
        title,
        re.I,
    )

    if size_match:
        size = (
            size_match.group(1)
            .replace(",", ".")
            + " ml"
        )

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": url,
        "available": True,
        "availability": "in_stock",
        **({"size": size} if size else {}),
    }


def _search_urls(query):
    q = quote_plus(query)

    return [
        f"{BASE}/search?q={q}&type=product",
        f"{BASE}/search?q={q}",
    ]


def search(query):
    query = str(query or "").strip()

    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    results = []
    seen_urls = set()

    # Per Liquid Brun usiamo anche le pagine dirette.
    # La ricerca Shopify può infatti non restituire tutti i prodotti.
    query_tokens = set(_norm(query).split())

    for required, urls in DIRECT_PRODUCTS:
        if set(required).issubset(query_tokens):
            for url in urls:
                if url.lower() in seen_urls:
                    continue

                try:
                    item = _extract_product_page(
                        session,
                        url,
                        query,
                    )
                except requests.RequestException:
                    item = None

                if item:
                    seen_urls.add(url.lower())
                    results.append(item)

    # Poi proviamo la ricerca Shopify per eventuali prodotti aggiuntivi.
    if not results or "liquid" not in query_tokens:
        for url in _search_urls(query):
            try:
                r = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException:
                continue

            if r.status_code != 200 or not r.text:
                continue

            page_results = _extract_page(
                r.text,
                query,
            )

            for item in page_results:
                key = item["url"].lower()

                if key in seen_urls:
                    continue

                seen_urls.add(key)
                results.append(item)

            if page_results:
                break

    results.sort(
        key=lambda x: (
            len(_norm(x["name"])),
            x["name"].lower(),
        )
    )

    return results[:20]


if __name__ == "__main__":
    for q in (
        "Liquid Brun",
        "Liquid Brun Limited Edition",
        "Rasasi Hawas",
        "Armaf Club de Nuit",
        "Afnan 9 PM Night Out",
        "French Avenue",
    ):
        print("\n" + "=" * 60)
        print("QUERY:", q)

        items = search(q)

        print("RISULTATI:", len(items))

        for item in items:
            print(item)

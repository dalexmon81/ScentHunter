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

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
)

NON_FRAGRANCE = (
    "body mist",
    "body spray",
    "body lotion",
    "body cream",
    "body oil",
    "shower gel",
    "shower oil",
    "hand and body",
    "deodorant",
    "after shave",
)

SIZE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b", re.I)


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _matches(text, query):
    hay = _norm(text)
    words = _tokens(query)
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
    except requests.RequestException as error:
        print(f"DELOOX ERROR: {error}")
        return None


def _find_brand_category(session, query):
    """
    Deloox non usa un normale /search?q=...
    La home espone invece l'indice dei brand.
    Cerchiamo il brand direttamente lì e apriamo la sua categoria.
    """
    response = _get(session, HOME_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    query_words = _tokens(query)

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

        # Il nome brand deve comparire nella query.
        if all(word in query_words for word in brand_words):
            candidates.append((len(brand_words), len(name), url))

    if not candidates:
        return None

    # Preferisci il brand più specifico.
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][2]


def _query_wants_non_fragrance(query):
    q = _norm(query)
    return any(term in q for term in NON_FRAGRANCE)


def _is_relevant_product(name, query):
    if not _matches(name, query):
        return False

    name_norm = _norm(name)

    # Se l'utente cerca semplicemente il profumo, elimina lotion/mist/gel ecc.
    if not _query_wants_non_fragrance(query):
        if any(term in name_norm for term in NON_FRAGRANCE):
            return False

    return True


def _extract_product_variants(html, product_name, product_url):
    """
    Estrae 30/50/100 ml ecc. dalla pagina del singolo profumo.
    Deloox mostra le varianti nella stessa pagina, ciascuna con il proprio prezzo.
    """
    soup = BeautifulSoup(html, "html.parser")
    strings = [_clean(x) for x in soup.stripped_strings if _clean(x)]

    results = []
    seen_sizes = set()

    for i, value in enumerate(strings):
        size_match = SIZE_RE.fullmatch(value)
        if not size_match:
            continue

        size = size_match.group(1).replace(",", ".")
        size_label = f"{size} ml"

        if size_label in seen_sizes:
            continue

        # Cerca il prezzo DOPO questa taglia, ma si ferma appena incontra
        # la taglia successiva. Così 30/50/100 ml non ricevono lo stesso prezzo.
        chunk = []
        sold_out = False

        for j in range(i + 1, min(i + 18, len(strings))):
            nxt = strings[j]

            if SIZE_RE.fullmatch(nxt):
                break

            chunk.append(nxt)

            low = nxt.lower()
            if any(word in low for word in SOLD_OUT):
                sold_out = True
                break

        if sold_out:
            continue

        joined = " ".join(chunk)
        price = _extract_price(joined)

        if not price:
            continue

        seen_sizes.add(size_label)

        # Il fragment rende ogni variante un risultato distinto senza cambiare
        # la pagina Deloox aperta dall'utente.
        slug = re.sub(r"[^a-z0-9]+", "-", size_label.lower()).strip("-")

        results.append({
            "store": STORE,
            "name": f"{product_name} {size_label}",
            "price": price,
            "url": f"{product_url}#{slug}",
            "available": True,
            "availability": "in_stock",
            "size": size_label,
        })

    return results

def _extract_category(html, query):
    """
    La pagina categoria Deloox contiene direttamente:
    nome prodotto, formato, disponibilità e prezzo.
    Usiamo la stessa filosofia semplice di PerfumeMarket:
    link -> pochi parent -> prezzo della stessa card.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    query_tokens = _tokens(query)

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        name = _clean(link.get_text(" ", strip=True))

        if not href:
            continue

        product_url = urljoin(BASE_URL, href).split("?")[0]

        if "/product/" not in product_url.lower():
            continue

        if not name:
            continue

        name_norm = _norm(name)

        if not all(token in name_norm for token in query_tokens):
            continue

        if not _is_relevant_product(name, query):
            continue

        node = link
        price = None
        card_text = ""

        for _ in range(6):
            if node is None:
                break

            card_text = _clean(node.get_text(" ", strip=True))
            price = _extract_price(card_text)

            if price:
                break

            node = node.parent

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue

        if not price:
            continue

        if product_url in seen:
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


def _extract_brand_page(html, query):
    """
    Alcune pagine brand mostrano i prodotti senza link /product/
    immediatamente leggibile. In quel caso prendiamo i blocchi testuali
    che contengono query + prezzo e recuperiamo il link prodotto vicino.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        if not href:
            continue

        node = link

        for _ in range(6):
            if node is None:
                break

            text = _clean(node.get_text(" ", strip=True))

            if _matches(text, query):
                price = _extract_price(text)

                if price and not any(x in text.lower() for x in SOLD_OUT):
                    product_link = None
                    product_name = ""

                    for a in node.find_all("a", href=True):
                        candidate_url = urljoin(BASE_URL, a.get("href", "")).split("?")[0]
                        candidate_name = _clean(a.get_text(" ", strip=True))

                        if "/product/" in candidate_url.lower():
                            product_link = candidate_url

                            if candidate_name and _matches(candidate_name, query):
                                product_name = candidate_name
                                break

                    if product_link:
                        if not product_name:
                            product_name = query

                        if product_link not in seen:
                            seen.add(product_link)
                            results.append({
                                "store": STORE,
                                "name": product_name,
                                "price": price,
                                "url": product_link,
                                "available": True,
                                "availability": "in_stock",
                            })

                break

            node = node.parent

    return results


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()

    # 1) Trova il brand dall'indice Deloox.
    brand_url = _find_brand_category(session, query)
    if not brand_url:
        return []

    # 2) Cerca il prodotto nella pagina brand.
    response = _get(session, brand_url)
    if response is None:
        return []

    category_results = _extract_category(response.text, query)

    if not category_results:
        category_results = _extract_brand_page(response.text, query)

    # 3) Scarta prodotti corpo/accessori e conserva solo candidati pertinenti.
    candidates = [
        item for item in category_results
        if _is_relevant_product(item.get("name", ""), query)
    ]

    if not candidates:
        return []

    # Preferisci il nome più corto: normalmente è il profumo principale,
    # non una variante/accessorio con parole aggiuntive.
    candidates.sort(key=lambda item: len(_norm(item.get("name", ""))))

    final_results = []
    seen = set()

    for item in candidates[:5]:
        clean_url = item["url"].split("#")[0].split("?")[0]
        product_response = _get(session, clean_url)

        if product_response is None:
            continue

        variants = _extract_product_variants(
            product_response.text,
            item["name"],
            clean_url,
        )

        for variant in variants:
            key = (_norm(variant["name"]), variant["price"])
            if key in seen:
                continue
            seen.add(key)
            final_results.append(variant)

        # Appena troviamo le varianti del profumo corretto non serve aprire
        # body mist/lotion o altri risultati omonimi.
        if variants:
            break

    # Fallback: se Deloox cambia temporaneamente markup, restituisce almeno
    # il profumo principale trovato nella categoria.
    if not final_results:
        return candidates[:1]

    return final_results[:20]


if __name__ == "__main__":
    for q in (
        "French Avenue Liquid Brun",
        "Miu Miu Miutine",
        "Rasasi Hawas Ice",
    ):
        print(q, search(q))

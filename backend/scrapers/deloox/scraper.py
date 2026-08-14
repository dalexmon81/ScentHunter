import json
import re
import unicodedata
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = f"{BASE_URL}/en"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

PRICE_RE = re.compile(
    r"""
    (?:
        €\s*(?P<euro_before>\d{1,4})\s*(?:[,.^]\s*)+(?P<cents_before>\d{2})\s*\^*
        |
        (?P<euro_after>\d{1,4})\s*(?:[,.^]\s*)+(?P<cents_after>\d{2})\s*\^*\s*€
        |
        €\s*(?P<integer_before>\d{1,4})(?![\d.,])
        |
        (?P<integer_after>\d{1,4})\s*€
    )
    """,
    re.I | re.X,
)

SOLD_OUT = (
    "sold out",
    "out of stock",
    "not available",
    "currently unavailable",
)

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "body oil",
    "body wash", "shower gel", "shower oil", "hand and body", "hand cream",
    "deodorant", "after shave", "aftershave", "hair mist", "hair spray", "soap",
)

SIZE_RE = re.compile(r"\b(\d{1,3}(?:[.,]\d+)?)\s*ml\b", re.I)
SIZE_FULL_RE = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)\s*ml$", re.I)

CATEGORY_FALLBACKS = (
    (("liquid", "brun"), "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"),
    (("french", "avenue"), "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"),
    (("le", "beau", "le", "parfum"), "https://www.deloox.com/category/1084243/le-beau-le-parfum.html"),
    (("jean", "paul", "gaultier"), "https://www.deloox.com/category/1072906/jean-paul-gaultier-fragrances.html"),
    (("miu", "miu"), "https://www.deloox.com/category/1071574/miu-miu-fragrances.html"),
)

NON_FRAGRANCE_TOKENS = {
    tuple(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    for value in NON_FRAGRANCE
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value):
    value = unicodedata.normalize("NFKD", _clean(value).lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(value):
    return [token for token in _norm(value).split() if len(token) > 1]


def _matches_soft(text, query, minimum=0.55):
    text_tokens = set(_tokens(text))
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False
    found = sum(token in text_tokens for token in query_tokens)
    return found / len(query_tokens) >= minimum


def _match_score(text, query):
    text_tokens = _tokens(text)
    query_tokens = _tokens(query)
    if not query_tokens:
        return -9999
    text_set = set(text_tokens)
    query_set = set(query_tokens)
    found = sum(token in text_set for token in query_set)
    if found == 0:
        return -9999
    missing = len(query_set) - found
    extras = [token for token in text_tokens if token not in query_set]
    return found * 100 - missing * 35 - len(extras) * 3 - abs(len(text_tokens) - len(query_tokens))


def _extract_price(text):
    if not text:
        return None
    match = PRICE_RE.search(_clean(text))
    if not match:
        return None
    if match.group("euro_before"):
        return f"{match.group('euro_before')},{match.group('cents_before')} €"
    if match.group("euro_after"):
        return f"{match.group('euro_after')},{match.group('cents_after')} €"
    if match.group("integer_before"):
        return f"{match.group('integer_before')},00 €"
    if match.group("integer_after"):
        return f"{match.group('integer_after')},00 €"
    return None


def _get(session, url):
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        return response
    except requests.RequestException as error:
        print(f"DELOOX ERROR: {error}")
        return None


def _query_wants_non_fragrance(query):
    query_tokens = set(_tokens(query))
    return any(set(phrase).issubset(query_tokens) for phrase in NON_FRAGRANCE_TOKENS)


def _contains_non_fragrance_product(text):
    tokens = _tokens(text)
    for phrase in NON_FRAGRANCE_TOKENS:
        size = len(phrase)
        for index in range(len(tokens) - size + 1):
            if tuple(tokens[index:index + size]) == phrase:
                return True
    return False


def _is_relevant_product(text, query):
    if not _matches_soft(text, query, minimum=0.55):
        return False
    if not _query_wants_non_fragrance(query) and _contains_non_fragrance_product(text):
        return False
    return True


def _find_brand_category(session, query):
    query_tokens = set(_tokens(query))

    if query_tokens == {"liquid", "brun"}:
        return "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html"

    if {"liquid", "brun", "limited", "edition"}.issubset(query_tokens):
        return "https://www.deloox.com/en/category/1132834/liquid-brun.html"

    for required_tokens, fallback_url in CATEGORY_FALLBACKS:
        if set(required_tokens).issubset(query_tokens):
            return fallback_url

    response = _get(session, HOME_URL)
    if response is None:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []

    for link in soup.find_all("a", href=True):
        name = _clean(link.get_text(" ", strip=True))
        href = _clean(link.get("href"))
        if not name or not href:
            continue
        url = urljoin(BASE_URL, href)
        if "/category/" not in url.lower():
            continue
        category_tokens = set(_tokens(name))
        overlap = len(category_tokens & query_tokens)
        if overlap:
            candidates.append((overlap, overlap / len(category_tokens), url))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _find_product_card(link):
    node = link
    for _ in range(8):
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if _extract_price(text) or SIZE_RE.search(text):
            return node
        node = node.parent
    return link


def _url_matches_query(product_url, query):
    url_tokens = set(_tokens(product_url))
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False
    if query_tokens.issubset(url_tokens):
        return True
    found = sum(1 for token in query_tokens if token in url_tokens)
    return found / len(query_tokens) >= 0.55


def _discover_category_pages(session, category_url, html, max_pages=5):
    """Trova pagine successive della categoria senza conoscere la struttura esatta."""
    pages = [category_url]
    seen = {category_url.split("#")[0].split("?")[0]}
    soup = BeautifulSoup(html, "html.parser")

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        url = urljoin(BASE_URL, href).split("#")[0]
        if "/category/" not in url.lower():
            continue
        label = _norm(link.get_text(" ", strip=True))
        href_norm = _norm(url)
        if (
            "next" in label
            or "pagina" in label
            or "page" in href_norm
            or "p=" in href.lower()
            or "page=" in href.lower()
        ):
            if url not in seen:
                seen.add(url)
                pages.append(url)
        if len(pages) >= max_pages:
            break

    return pages


def _candidate_name_matches(link, card, query):
    """Il nome del prodotto deve essere ricavato dal link/titolo/heading, non dal breadcrumb."""
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False

    values = [
        _clean(link.get_text(" ", strip=True)),
        _clean(link.get("title") or ""),
        _clean(link.get("aria-label") or ""),
    ]

    for tag in ("h1", "h2", "h3", "h4"):
        node = card.find(tag)
        if node:
            values.append(_clean(node.get_text(" ", strip=True)))

    for value in values:
        if not value or SIZE_FULL_RE.fullmatch(value):
            continue
        tokens = set(_tokens(value))
        if query_tokens.issubset(tokens):
            return True

    return False


def _extract_category_candidates(html, query):
    """Scoperta più ampia: URL = candidato, nome del prodotto = criterio."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0].split("#")[0]
        if "/product/" not in product_url.lower():
            continue

        card = _find_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue
        if not _candidate_name_matches(link, card, query):
            continue

        # Evita prodotti non-profumo ma non richiede più che l'URL contenga
        # le parole della query: il nome reale della scheda è la prova.
        product_name = (
            _clean(link.get_text(" ", strip=True))
            or _clean(link.get("title") or "")
        )
        if not product_name or SIZE_FULL_RE.fullmatch(product_name):
            for tag in ("h1", "h2", "h3", "h4"):
                node = card.find(tag)
                if node:
                    product_name = _clean(node.get_text(" ", strip=True))
                    if product_name:
                        break

        if not product_name:
            continue
        if not _is_relevant_product(product_name, query):
            continue

        price = _extract_price(card_text)
        if not price:
            continue

        if product_url in seen:
            continue
        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results

def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    query_tokens = set(_tokens(query))

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        product_url = urljoin(BASE_URL, href).split("?")[0]
        if "/product/" not in product_url.lower():
            continue
        if not _url_matches_query(product_url, query):
            continue

        card = _find_product_card(link)
        card_text = _clean(card.get_text(" ", strip=True))

        if any(word in card_text.lower() for word in SOLD_OUT):
            continue
        if not _matches_soft(card_text, query, minimum=0.55):
            continue

        card_tokens = set(_tokens(card_text))
        if not query_tokens.issubset(card_tokens):
            if not _matches_soft(card_text, query, minimum=0.75):
                link_title = _clean(link.get("title") or "")
                if not (link_title and query_tokens.issubset(set(_tokens(link_title)))):
                    heading = None
                    for tag in ("h1", "h2", "h3", "h4"):
                        node_h = card.find(tag)
                        if node_h:
                            heading = _clean(node_h.get_text(" ", strip=True))
                            break
                    if not (heading and query_tokens.issubset(set(_tokens(heading)))):
                        continue

        if not _is_relevant_product(card_text, query):
            continue

        price = _extract_price(card_text)
        if not price:
            continue

        product_name = query
        link_name = _clean(link.get_text(" ", strip=True))
        if (
            link_name
            and not SIZE_FULL_RE.fullmatch(link_name)
            and _matches_soft(link_name, query, minimum=0.55)
            and query_tokens.issubset(set(_tokens(link_name)))
        ):
            product_name = link_name
        else:
            link_title = _clean(link.get("title") or "")
            if link_title and query_tokens.issubset(set(_tokens(link_title))):
                product_name = link_title

        if product_url in seen:
            continue
        seen.add(product_url)

        results.append({
            "store": STORE,
            "name": product_name,
            "price": price,
            "url": product_url,
            "available": True,
            "availability": "in_stock",
        })

    return results


def _extract_brand_page(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        node = link

        for _ in range(8):
            if node is None:
                break

            text = _clean(node.get_text(" ", strip=True))
            if not _matches_soft(text, query, minimum=0.55):
                node = node.parent
                continue

            price = _extract_price(text)
            if not price:
                node = node.parent
                continue

            if any(word in text.lower() for word in SOLD_OUT):
                node = node.parent
                continue

            product_link = None
            for anchor in node.find_all("a", href=True):
                candidate_url = urljoin(BASE_URL, anchor.get("href", "")).split("?")[0]
                if "/product/" not in candidate_url.lower():
                    continue
                if not _url_matches_query(candidate_url, query):
                    continue
                product_link = candidate_url
                break

            if (
                product_link
                and product_link not in seen
                and _is_relevant_product(text, query)
            ):
                seen.add(product_link)
                results.append({
                    "store": STORE,
                    "name": query,
                    "price": price,
                    "url": product_link,
                    "available": True,
                    "availability": "in_stock",
                })
            break

    return results


def _page_product_names(html):
    """Extract authoritative product names from the product page."""
    soup = BeautifulSoup(html, "html.parser")
    names = []

    for node in soup.find_all("h1"):
        value = _clean(node.get_text(" ", strip=True))
        if value:
            names.append(value)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = str(item.get("@type", "")).lower()
            if item_type == "product":
                value = _clean(item.get("name"))
                if value:
                    names.append(value)

            for key in ("mainEntity", "item", "@graph"):
                child = item.get(key)
                if child:
                    stack.extend(child if isinstance(child, list) else [child])

    # Keep order and remove duplicates.
    unique = []
    seen = set()
    for name in names:
        key = _norm(name)
        if key and key not in seen:
            seen.add(key)
            unique.append(name)
    return unique


def _page_matches_query(html, query):
    """
    FINAL PRODUCT-ID CHECK.

    The category/URL search is only discovery. Before a Deloox link is returned,
    the actual product page must identify itself as the requested product.
    This blocks cases where a category result/redirect points to a different
    fragrance (for example Le Beau -> Le Male).
    """
    names = _page_product_names(html)
    if not names:
        return False

    # Prefer an exact token match; never accept a page merely because the URL
    # contains some of the requested words.
    query_tokens = set(_tokens(query))
    if not query_tokens:
        return False

    for name in names:
        name_tokens = set(_tokens(name))
        if query_tokens.issubset(name_tokens):
            if _is_relevant_product(name, query):
                return True

    # A small fallback is allowed for generic searches such as "Le Beau",
    # where the product page may append concentration/size/marketing text.
    return any(_matches_soft(name, query, minimum=0.80) for name in names)


def _extract_product_variants(html, product_name, product_url):
    soup = BeautifulSoup(html, "html.parser")
    strings = [_clean(value) for value in soup.stripped_strings if _clean(value)]

    results = []
    seen_sizes = set()

    for index, value in enumerate(strings):
        size_match = SIZE_FULL_RE.fullmatch(value)
        if not size_match:
            continue

        size = size_match.group(1).replace(",", ".")
        size_label = f"{size} ml"

        if size_label in seen_sizes:
            continue

        chunk = []
        sold_out = False
        for next_index in range(index + 1, min(index + 30, len(strings))):
            next_value = strings[next_index]
            if SIZE_FULL_RE.fullmatch(next_value):
                break
            chunk.append(next_value)
            if any(word in next_value.lower() for word in SOLD_OUT):
                sold_out = True
                break

        if sold_out:
            continue

        price = _extract_price(" ".join(chunk))
        if not price:
            continue

        seen_sizes.add(size_label)
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


def _extract_jsonld_variants(html, product_name, product_url):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue

        objects = data if isinstance(data, list) else [data]
        for item in objects:
            if not isinstance(item, dict):
                continue

            item_text = " ".join([
                str(item.get("name", "")),
                str(item.get("description", "")),
            ])
            size_match = SIZE_RE.search(item_text)
            if not size_match:
                continue

            size = size_match.group(1).replace(",", ".")
            offers = item.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]

            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = offer.get("price")
                if price is None:
                    continue
                if str(offer.get("priceCurrency", "EUR")) != "EUR":
                    continue
                availability = str(offer.get("availability", "")).lower()
                if "outofstock" in availability:
                    continue

                price_text = str(price).replace(".", ",")
                if "," not in price_text:
                    price_text += ",00"

                results.append({
                    "store": STORE,
                    "name": f"{product_name} {size} ml",
                    "price": f"{price_text} €",
                    "url": product_url,
                    "available": True,
                    "availability": "in_stock",
                    "size": f"{size} ml",
                })

    return results


def _size_number(item):
    match = SIZE_RE.search(item.get("size", ""))
    if not match:
        return 9999
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return 9999


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        category_url = _find_brand_category(session, query)
        if not category_url:
            return []

        response = _get(session, category_url)
        if response is None:
            return []

        # Prima scoperta: usiamo il nome reale del candidato, non il solo URL.
        candidates = _extract_category_candidates(response.text, query)

        # Se la categoria contiene paginazione, cerchiamo anche nelle pagine
        # successive: il primo candidato sbagliato non deve chiudere la ricerca.
        if not candidates:
            for page_url in _discover_category_pages(
                session, category_url, response.text, max_pages=5
            )[1:]:
                page_response = _get(session, page_url)
                if page_response is None:
                    continue
                candidates.extend(
                    _extract_category_candidates(page_response.text, query)
                )

        if not candidates:
            candidates = _extract_category(response.text, query)
        if not candidates:
            candidates = _extract_brand_page(response.text, query)
        if not candidates:
            return []

        scored = []
        seen_urls = set()

        for item in candidates:
            product_url = item["url"].split("#")[0].split("?")[0]
            if product_url in seen_urls:
                continue
            # O URL matching è solo un filtro ausiliario. La prova decisiva
            # sarà il nome reale della página do produto.
            seen_urls.add(product_url)
            scored.append((_match_score(item["name"], query), item))

        if not scored:
            return []

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score = scored[0][0]
        minimum_score = best_score - 45

        final_results = []
        seen_variants = set()

        for score, item in scored:
            # Non fermarsi al primo punteggio: il candidato migliore può essere
            # una pagina sbagliata. Verifichiamo tutti i candidati rilevanti.
            product_url = item["url"].split("#")[0].split("?")[0]
            product_response = _get(session, product_url)
            if product_response is None:
                continue

            # NEW: verify the real product page before exposing any offer.
            if not _page_matches_query(product_response.text, query):
                continue

            variants = _extract_product_variants(
                product_response.text,
                item["name"],
                product_url,
            )
            if not variants:
                variants = _extract_jsonld_variants(
                    product_response.text,
                    item["name"],
                    product_url,
                )

            for variant in variants:
                key = (
                    variant["url"],
                    variant.get("size", ""),
                    variant["price"],
                )
                if key in seen_variants:
                    continue
                seen_variants.add(key)
                final_results.append(variant)

        if final_results:
            final_results.sort(key=_size_number)
            return final_results[:20]

        # IMPORTANT: do not fall back to unverified candidates.
        # The old fallback could return a wrong product link after the
        # variant extraction failed.
        return []

    finally:
        session.close()


if __name__ == "__main__":
    queries = (
        "Tom Ford Neroli Portofino",
        "Miu Miu Miutine",
        "Le Beau Le Parfum",
        "Jean Paul Gaultier Le Beau Le Parfum",
        "Rasasi Hawas Ice",
    )

    for query in queries:
        print("\nQUERY:", query)
        results = search(query)
        if not results:
            print("NESSUN RISULTATO")
        else:
            for result in results:
                print(result)

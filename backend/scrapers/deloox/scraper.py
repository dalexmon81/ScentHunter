import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
HOME_URL = BASE_URL + "/en"
TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
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


def _matches(text, query):
    hay = _norm(text)
    words = _tokens(query)
    return bool(words) and all(word in hay for word in words)


def _extract_price(text):
    match = PRICE_RE.search(text or "")
    if not match:
        return None
    return f"{match.group(1)},{match.group(2)} €"


def _extract_ml(text):
    m = ML_RE.search(text or "")
    return int(m.group(1)) if m else None


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
        if brand_words and all(word in query_words for word in brand_words):
            candidates.append((len(brand_words), len(name), url))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (-x[0], -x[1]))
    return candidates[0][2]


def _canonical_url(url):
    return url.split("#")[0].split("?")[0].rstrip("/")


def _variant_key(item):
    """
    Un solo risultato per formato.
    Se il formato non è disponibile, usa URL + nome.
    """
    ml = item.get("ml")
    if ml:
        return ("ml", ml)
    return ("url", _canonical_url(item.get("url", "")), _norm(item.get("name", "")))


def _add_result(results, seen, name, price, url, text=""):
    if not price or not url:
        return

    if any(word in (text or "").lower() for word in SOLD_OUT):
        return

    ml = _extract_ml(name) or _extract_ml(text)

    item = {
        "store": STORE,
        "name": _clean(name),
        "price": price,
        "url": _canonical_url(url),
        "available": True,
        "availability": "in_stock",
    }

    if ml:
        item["ml"] = ml
        # Forza il formato nel nome solo se manca.
        if not _extract_ml(item["name"]):
            item["name"] = f'{item["name"]} {ml} ml'

    key = _variant_key(item)
    if key in seen:
        return

    seen.add(key)
    results.append(item)


def _extract_json_variants(soup, query, page_url):
    """
    Cerca varianti anche nei JSON/JSON-LD presenti nella pagina.
    Utile quando 30/50/100 ml non sono tre card HTML separate.
    """
    results = []
    seen = set()

    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        if not raw or ("ml" not in raw.lower() and "price" not in raw.lower()):
            continue

        # JSON-LD puro
        if (script.get("type") or "").lower() == "application/ld+json":
            try:
                data = json.loads(raw)
            except Exception:
                data = None

            stack = data if isinstance(data, list) else [data]
            for obj in stack:
                if not isinstance(obj, dict):
                    continue

                candidates = []
                if isinstance(obj.get("offers"), list):
                    candidates.extend(obj["offers"])
                elif isinstance(obj.get("offers"), dict):
                    candidates.append(obj["offers"])

                base_name = _clean(obj.get("name", ""))
                if base_name and not _matches(base_name, query):
                    continue

                for offer in candidates:
                    if not isinstance(offer, dict):
                        continue

                    price_raw = str(offer.get("price", "")).replace(".", ",")
                    if not re.fullmatch(r"\d{1,4},\d{2}", price_raw):
                        continue

                    offer_url = urljoin(page_url, str(offer.get("url") or page_url))
                    desc = " ".join(
                        str(offer.get(k, ""))
                        for k in ("name", "description", "sku")
                    )
                    ml = _extract_ml(desc) or _extract_ml(base_name)

                    if not ml:
                        continue

                    name = base_name
                    if not _extract_ml(name):
                        name = f"{name} {ml} ml"

                    _add_result(
                        results, seen, name,
                        price_raw + " €", offer_url, desc
                    )

        # Fallback: cerca finestre testuali attorno ai formati.
        # Serve per JSON JS non perfettamente parsabile.
        for m in ML_RE.finditer(raw):
            start = max(0, m.start() - 450)
            end = min(len(raw), m.end() + 450)
            chunk = raw[start:end]

            if not _matches(chunk, query):
                continue

            price = _extract_price(chunk)
            if not price:
                # JSON spesso salva il prezzo come 105.49
                pm = re.search(
                    r'["\'](?:price|currentPrice|sellingPrice)["\']\s*:\s*["\']?(\d{1,4})[.,](\d{2})',
                    chunk, re.I
                )
                if pm:
                    price = f"{pm.group(1)},{pm.group(2)} €"

            if not price:
                continue

            ml = int(m.group(1))
            _add_result(
                results, seen,
                f"{query} {ml} ml",
                price,
                page_url,
                chunk
            )

    return results


def _extract_product_variants(session, product_url, query):
    """
    Apre la pagina prodotto trovata e recupera i veri formati:
    30 ml, 50 ml, 100 ml ecc.
    """
    response = _get(session, product_url)
    if response is None:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    seen = set()

    h1 = soup.find("h1")
    base_name = _clean(h1.get_text(" ", strip=True)) if h1 else query

    # 1. Varianti visibili: link, button, option, label.
    selectors = ["a", "button", "option", "label"]
    for tag in soup.find_all(selectors):
        text = _clean(tag.get_text(" ", strip=True))
        ml = _extract_ml(text)

        if not ml:
            continue

        # Risali poco per trovare prezzo e contesto della variante.
        node = tag
        block_text = text
        price = _extract_price(text)

        for _ in range(5):
            if price:
                break
            node = getattr(node, "parent", None)
            if node is None:
                break
            block_text = _clean(node.get_text(" ", strip=True))
            if len(block_text) > 2500:
                break
            price = _extract_price(block_text)

        href = tag.get("href") if hasattr(tag, "get") else None
        variant_url = urljoin(product_url, href) if href else product_url

        if price:
            name = base_name
            if not _extract_ml(name):
                name = f"{name} {ml} ml"
            _add_result(
                results, seen, name, price,
                variant_url, block_text
            )

    # 2. Dati strutturati / JSON.
    for item in _extract_json_variants(soup, query, product_url):
        key = _variant_key(item)
        if key not in seen:
            seen.add(key)
            results.append(item)

    # 3. Se la pagina stessa è un singolo formato.
    page_text = _clean(soup.get_text(" ", strip=True))
    page_ml = _extract_ml(base_name)
    page_price = None

    if page_ml:
        # Evita di prendere un prezzo casuale da tutta la pagina:
        # prova prima elementi prezzo.
        for el in soup.select(
            "[class*='price'], [id*='price'], [itemprop='price'], [data-price]"
        ):
            price = _extract_price(_clean(el.get_text(" ", strip=True)))
            if price:
                page_price = price
                break

        if page_price:
            _add_result(
                results, seen, base_name, page_price,
                product_url, page_text[:1500]
            )

    return results


def _extract_category(html, query):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    seen = set()
    product_urls = []

    query_tokens = _tokens(query)

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        name = _clean(link.get_text(" ", strip=True))

        if not href:
            continue

        product_url = _canonical_url(urljoin(BASE_URL, href))

        if "/product/" not in product_url.lower():
            continue

        # Il testo dell'anchor può essere vuoto: usa anche alt/title/card.
        img = link.find("img")
        alt = _clean(img.get("alt")) if img else ""
        title = _clean(link.get("title"))
        candidate_name = name or title or alt

        node = link
        card_text = candidate_name
        price = None

        for _ in range(6):
            if node is None:
                break
            card_text = _clean(node.get_text(" ", strip=True))
            if len(card_text) > 2500:
                break
            if not price:
                price = _extract_price(card_text)
            node = node.parent

        searchable = " ".join((candidate_name, card_text))
        if not all(token in _norm(searchable) for token in query_tokens):
            continue

        if product_url not in product_urls:
            product_urls.append(product_url)

        if price:
            final_name = candidate_name or query
            _add_result(
                results, seen, final_name,
                price, product_url, card_text
            )

    return results, product_urls


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    brand_url = _find_brand_category(session, query)
    if not brand_url:
        return []

    response = _get(session, brand_url)
    if response is None:
        return []

    category_results, product_urls = _extract_category(response.text, query)

    # Il risultato della categoria serve soprattutto come porta d'ingresso.
    # Apriamo ogni prodotto candidato per scoprire TUTTI i formati reali.
    all_results = []
    seen = set()

    for product_url in product_urls[:12]:
        variants = _extract_product_variants(session, product_url, query)
        for item in variants:
            key = _variant_key(item)
            if key in seen:
                continue
            seen.add(key)
            all_results.append(item)

    # Se la pagina prodotto non espone varianti leggibili,
    # mantieni almeno i risultati validi della categoria.
    if not all_results:
        for item in category_results:
            key = _variant_key(item)
            if key in seen:
                continue
            seen.add(key)
            all_results.append(item)

    # Deduplica finale per formato e ordina 30, 50, 100...
    deduped = []
    used_ml = set()
    used_other = set()

    for item in all_results:
        ml = item.get("ml") or _extract_ml(item.get("name", ""))
        if ml:
            if ml in used_ml:
                continue
            used_ml.add(ml)
            item["ml"] = ml
        else:
            key = (_canonical_url(item.get("url", "")), _norm(item.get("name", "")))
            if key in used_other:
                continue
            used_other.add(key)

        deduped.append(item)

    deduped.sort(key=lambda x: (
        x.get("ml") is None,
        x.get("ml") or 99999,
        _norm(x.get("name", ""))
    ))

    return deduped[:20]


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

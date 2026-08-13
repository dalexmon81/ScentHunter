import json
import re
import time
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SITEMAP_CACHE = None
SITEMAP_CACHE_TIME = 0.0
SITEMAP_CACHE_SECONDS = 900
RESULT_CACHE = {}
RESULT_CACHE_SECONDS = 90
REQUEST_TIMEOUT = 4
MAX_CANDIDATES = 6
MAX_WORKERS = 4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

IGNORED_MATCH_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "spray", "ml", "pour", "for",
}

PRICE_RE = re.compile(r"(\d{1,5}[.,]\d{2})\s*€")
SIZE_RE = re.compile(r"\b(\d{1,4})\s*ml\b", re.I)

OLD_CLASS_RE = re.compile(
    r"(?:old|was|strike|struck|compare|cross|previous|original|uvp|list-price|regular-price)",
    re.I,
)

CURRENT_CLASS_RE = re.compile(
    r"(?:current|now|final|sale-price|selling-price|product-price|price-current|price-now|price--current)",
    re.I,
)

COUPON_WORDS = (
    "sale5de", "coupon", "gutschein", "rabattcode", "rabatt", "promo",
    "promotion", "aktion", "discount code", "discountcode", "voucher",
    "preis inkl. code", "preis inkl code", "inkl. code", "inkl code",
)

UNAVAILABLE_PHRASES = (
    "leider nicht lieferbar",
    "nicht lieferbar",
    "nicht vorrätig",
    "ausverkauft",
)


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text or ""))
        if len(x) > 1
    ]


def _all_tokens_match(text, query):
    text_tokens = set(_tokens(text))
    query_tokens = {
        token
        for token in _tokens(query)
        if token not in IGNORED_MATCH_WORDS
    }

    if not query_tokens:
        query_tokens = set(_tokens(query))

    if not query_tokens:
        return False

    return query_tokens.issubset(text_tokens)


def _xml_urls(xml_text):
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _new_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _get_sitemap_urls():
    global SITEMAP_CACHE, SITEMAP_CACHE_TIME

    now = time.time()
    if SITEMAP_CACHE is not None and now - SITEMAP_CACHE_TIME < SITEMAP_CACHE_SECONDS:
        print(f"PARFUMZENTRUM: SITEMAP_CACHE_HIT urls={len(SITEMAP_CACHE)}", flush=True)
        return SITEMAP_CACHE

    session = _new_session()
    try:
        print("PARFUMZENTRUM: SITEMAP_GET_START", flush=True)
        r = session.get(SITEMAP_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code in (403, 429):
            print(f"PARFUMZENTRUM: SITEMAP_BLOCKED HTTP={r.status_code}", flush=True)
            return []
        r.raise_for_status()
        urls = _xml_urls(r.text)

        child_maps = [
            u for u in urls
            if "sitemap" in u.lower()
            and u.lower().endswith((".xml", ".xml.gz"))
        ]

        if not child_maps:
            SITEMAP_CACHE = urls
            SITEMAP_CACHE_TIME = now
            return urls

        out = []
        for sm in child_maps:
            try:
                rr = session.get(sm, timeout=REQUEST_TIMEOUT)
                if rr.status_code == 200:
                    out.extend(_xml_urls(rr.text))
            except requests.RequestException as exc:
                print(f"PARFUMZENTRUM: SITEMAP_CHILD_ERROR {type(exc).__name__}", flush=True)

        SITEMAP_CACHE = out
        SITEMAP_CACHE_TIME = now
        print(f"PARFUMZENTRUM: SITEMAP_READY urls={len(out)}", flush=True)
        return out
    finally:
        session.close()


def _parse_price(value):
    if value is None:
        return None

    m = PRICE_RE.search(str(value))
    if not m:
        # JSON/data attributes often contain only the numeric value.
        m = re.search(r"\b(\d{1,5}[.,]\d{2})\b", str(value))

    if not m:
        return None

    return m.group(1).replace(".", ",") + "€"


def _numeric_price(value):
    parsed = _parse_price(value)
    if not parsed:
        return None
    return float(parsed[:-1].replace(",", "."))


def _class_text(node):
    return " ".join(node.get("class") or [])


def _is_old_price_node(node):
    if node is None:
        return True
    if node.name in ("del", "s", "strike"):
        return True
    return bool(OLD_CLASS_RE.search(_class_text(node)))


def _has_coupon_indicator(text):
    low = str(text or "").lower()
    return any(word in low for word in COUPON_WORDS)


def _local_coupon_indicator(node, stop_node=None):
    """
    Riconosce un prezzo coupon solo quando il coupon appartiene realmente
    al nodo del prezzo. Non analizziamo il testo dei parent, perché il blocco
    della variante può contenere contemporaneamente prezzo normale e prezzo
    "Preis inkl. Code" come elementi fratelli.
    """
    if node is None:
        return False

    if _has_coupon_indicator(node.get_text(" ", strip=True)):
        return True

    classes = _class_text(node).lower()
    node_id = str(node.get("id") or "").lower()
    marker = f"{classes} {node_id}"
    return _has_coupon_indicator(marker)


def _price_from_element(node, stop_node=None):
    """Restituisce un prezzo valido da un elemento, oppure None."""
    if node is None or _is_old_price_node(node):
        return None

    if _local_coupon_indicator(node, stop_node):
        return None

    # Prezzi strutturati: preferiti al testo visuale.
    for attr in (
        "content",
        "data-price",
        "data-product-price",
        "data-final-price",
        "data-price-amount",
        "data-priceamount",
    ):
        value = node.get(attr)
        if value:
            price = _parse_price(value)
            if price:
                return price

    text = node.get_text(" ", strip=True)
    if "€" not in text:
        return None

    # Un contenitore generico che include un prezzo barrato non può essere
    # usato come fonte del prezzo: altrimenti un fallback sull'ancestor può
    # trasformare il vecchio prezzo in prezzo corrente. Il prezzo corrente
    # verrà trovato sul nodo più piccolo dedicato.
    if node.find(["del", "s", "strike"]):
        return None

    if any(_is_old_price_node(el) for el in node.find_all(True)):
        return None

    return _parse_price(text)


def _valid_price_elements(container):
    """Raccoglie prezzi correnti nel solo contenitore della variante."""
    candidates = []

    for el in container.find_all(True):
        if _is_old_price_node(el):
            continue

        cls = _class_text(el)
        price = _price_from_element(el, stop_node=container)
        if not price:
            continue

        # Il testo coupon non deve mai diventare il prezzo della variante.
        if _has_coupon_indicator(el.get_text(" ", strip=True)):
            continue

        score = 0
        if el.get("itemprop") == "price":
            score += 100
        if any(el.get(attr) for attr in (
            "data-price", "data-product-price", "data-final-price",
            "data-price-amount", "data-priceamount",
        )):
            score += 90
        if CURRENT_CLASS_RE.search(cls):
            score += 80
        if "price" in cls.lower():
            score += 20

        # Preferiamo elementi piccoli: un div enorme può contenere più prezzi.
        score -= min(len(el.get_text(" ", strip=True)), 300) / 1000
        candidates.append((score, price, el))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates


def _find_variant_container(size_node):
    """
    Trova il blocco DOM più vicino che rappresenta il formato.

    Partiamo dal nodo che contiene "100 ml" / "50 ml" e saliamo pochi livelli.
    Il primo contenitore che contiene un prezzo valido è quello preferito.
    """
    current = size_node.parent

    for _ in range(5):
        if current is None:
            break

        if _valid_price_elements(current):
            return current

        current = current.parent

    return None


def _extract_visible_variants(soup):
    """
    Estrae le coppie FORMATO -> PREZZO dal DOM visibile.

    Regole fondamentali:
    - <del>/<s>/<strike> e classi old/was/strike/compare sono ignorati;
    - prezzi coupon/promozionali con codice sono ignorati;
    - il prezzo corrente viene preso dal contenitore più vicino al formato;
    - non prendiamo mai semplicemente il primo "numero + €" della pagina.
    """
    variants = {}
    size_nodes = []

    for el in soup.find_all(True):
        text = el.get_text(" ", strip=True)
        if not text or not SIZE_RE.search(text):
            continue

        # Un elemento molto grande può contenere tutti i formati. Usiamo solo
        # elementi che rappresentano una singola etichetta di formato quando
        # possibile.
        matches = list(SIZE_RE.finditer(text))
        if len(matches) != 1:
            continue

        size_nodes.append((el, int(matches[0].group(1))))

    # Preferisci i nodi più piccoli, che sono più vicini alla label del formato.
    size_nodes.sort(key=lambda item: len(item[0].get_text(" ", strip=True)))

    for size_node, size_ml in size_nodes:
        if size_ml in variants:
            continue

        container = _find_variant_container(size_node)
        if container is None:
            continue

        prices = _valid_price_elements(container)
        if not prices:
            continue

        # Non accettiamo un contenitore che contiene un altro formato: sarebbe
        # ambiguo e potrebbe associare il prezzo sbagliato.
        container_sizes = {
            int(m.group(1))
            for m in SIZE_RE.finditer(container.get_text(" ", strip=True))
        }
        if len(container_sizes) > 1:
            continue

        variants[size_ml] = prices[0][1]

    return dict(sorted(variants.items()))


def _jsonld_variants(soup):
    """Estrae offerte JSON-LD solo quando il formato è esplicitamente riconoscibile."""
    out = []

    def size_from_text(*values):
        text = " ".join(str(v or "") for v in values)
        match = SIZE_RE.search(text)
        return int(match.group(1)) if match else None

    def walk(obj, parent=None):
        if isinstance(obj, dict):
            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    price = _parse_price(offer.get("price"))
                    if not price:
                        continue
                    size = size_from_text(
                        offer.get("name"),
                        offer.get("description"),
                        offer.get("sku"),
                        offer.get("url"),
                        obj.get("name"),
                        obj.get("description"),
                        obj.get("sku"),
                        obj.get("url"),
                    )
                    out.append((size, price))

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value, obj)

        elif isinstance(obj, list):
            for value in obj:
                if isinstance(value, (dict, list)):
                    walk(value, parent)

    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        walk(payload)

    return out


def _extract_global_price(soup, chunks):
    """Fallback per prodotti senza varianti esplicite."""
    # 1) itemprop/data-price, escludendo sempre old/coupon.
    structured = []
    for el in soup.find_all(True):
        if _is_old_price_node(el):
            continue
        if _local_coupon_indicator(el):
            continue
        if el.get("itemprop") == "price" or any(el.get(a) for a in (
            "data-price", "data-product-price", "data-final-price",
            "data-price-amount", "data-priceamount",
        )):
            price = _price_from_element(el)
            if price:
                structured.append(price)

    if structured:
        return structured[0]

    # 2) JSON-LD solo se espone una sola offerta: con più formati NON
    # scegliamo arbitrariamente il primo prezzo.
    jsonld = _jsonld_variants(soup)
    known_sizes = {size for size, _ in jsonld if size is not None}
    if len(known_sizes) <= 1 and jsonld:
        return jsonld[0][1]

    # 3) Fallback testuale molto stretto, senza coupon/old.
    for piece in chunks:
        if "€" not in piece:
            continue
        low = piece.lower()
        if _has_coupon_indicator(low):
            continue
        if any(k in low for k in ("statt", "vorher", "uvp", "original", "durchgestrichen")):
            continue
        m = PRICE_RE.search(piece)
        if m:
            return m.group(1).replace(".", ",") + "€"

    return None


def _extract_product(url, query):
    session = _new_session()
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)

        if r.status_code in (403, 429):
            print(f"PARFUMZENTRUM PRODUCT BLOCKED: HTTP {r.status_code}")
            r.close()
            return []

        if r.status_code != 200:
            r.close()
            return []

        html = r.text
        r.close()

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")

        if not h1:
            return []

        name = " ".join(h1.stripped_strings)

        if not _all_tokens_match(name, query):
            return []

        chunks = []
        node = h1

        for _ in range(8):
            if not node:
                break

            txt = node.get_text(" ", strip=True)

            if txt:
                chunks.append(txt)

            node = node.parent

        page_near_h1 = " ".join(chunks[:5]).lower()

        if any(x in page_near_h1 for x in UNAVAILABLE_PHRASES):
            return []

        # Prima cosa: estraiamo tutte le varianti realmente visibili.
        variants = _extract_visible_variants(soup)

        # Se il DOM non espone le coppie formato/prezzo, usiamo JSON-LD solo per
        # formati esplicitamente identificabili. Non inventiamo il formato.
        if not variants:
            for size, price in _jsonld_variants(soup):
                if size is not None:
                    variants[size] = price

        if variants:
            results = []
            for size_ml, price in sorted(variants.items()):
                results.append({
                    "store": "ParfumZentrum",
                    # Il formato nel nome serve anche a mantenere distinte le
                    # varianti nel dedup del backend; la UI lo rimuove dal nome
                    # visualizzato e usa size_ml per creare i gruppi.
                    "name": f"{name} {size_ml} ml",
                    "size_ml": str(size_ml),
                    "price": price,
                    "url": url,
                })
            return results

        # Nessuna variante esplicita: fallback a un solo prezzo sicuro.
        price = _extract_global_price(soup, chunks)
        if not price:
            return []

        return [{
            "store": "ParfumZentrum",
            "name": name,
            "price": price,
            "url": url,
        }]
    finally:
        session.close()

def search(query):
    query = str(query or "").strip()
    if not query:
        return []

    cache_key = query.lower()
    cached = RESULT_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < RESULT_CACHE_SECONDS:
        print(f"PARFUMZENTRUM: CACHE_HIT query={query!r} count={len(cached[1])}", flush=True)
        return [dict(item) for item in cached[1]]

    started = time.time()
    print(f"PARFUMZENTRUM: SEARCH_START query={query!r}", flush=True)

    try:
        urls = _get_sitemap_urls()
    except Exception as exc:
        print(f"PARFUMZENTRUM: SITEMAP_ERROR {type(exc).__name__}: {exc}", flush=True)
        return []

    candidates = [
        url for url in urls
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query)
    ]
    candidates = candidates[:MAX_CANDIDATES]
    print(f"PARFUMZENTRUM: CANDIDATES count={len(candidates)}", flush=True)

    results = []
    seen = set()
    if candidates:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(candidates))) as executor:
            future_map = {executor.submit(_extract_product, url, query): url for url in candidates}
            for future in as_completed(future_map):
                url = future_map[future]
                try:
                    items = future.result() or []
                except Exception as exc:
                    print(f"PARFUMZENTRUM: PRODUCT_ERROR url={url} error={type(exc).__name__}: {exc}", flush=True)
                    continue
                for item in items:
                    if not item:
                        continue
                    key = (item.get("name", "").lower(), item.get("url", ""), item.get("size_ml", ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(item)
                    print(
                        f"PARFUMZENTRUM: RESULT name={item.get('name')!r} size={item.get('size_ml')} price={item.get('price')}",
                        flush=True,
                    )

    results.sort(key=lambda x: (x.get("name", "").lower(), int(x.get("size_ml") or 0)))
    RESULT_CACHE[cache_key] = (time.time(), [dict(item) for item in results])
    print(f"PARFUMZENTRUM: SEARCH_COMPLETE count={len(results)} elapsed={time.time()-started:.2f}s", flush=True)
    return results


if __name__ == "__main__":
    results = search("Rasasi Hawas For Him")
    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)

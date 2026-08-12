import json
import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()

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


def _get_sitemap_urls():
    r = SESSION.get(SITEMAP_URL, headers=HEADERS, timeout=4)

    if r.status_code in (403, 429):
        print(f"PARFUMZENTRUM BLOCKED: HTTP {r.status_code}")
        r.close()
        return []

    r.raise_for_status()
    xml_text = r.text
    r.close()
    urls = _xml_urls(xml_text)

    child_maps = [
        u for u in urls
        if "sitemap" in u.lower()
        and u.lower().endswith((".xml", ".xml.gz"))
    ]

    if not child_maps:
        return urls

    out = []

    for sm in child_maps:
        try:
            rr = SESSION.get(sm, headers=HEADERS, timeout=4)

            if rr.status_code in (403, 429):
                print(f"PARFUMZENTRUM SITEMAP BLOCKED: HTTP {rr.status_code}")
                rr.close()
                break

            if rr.status_code == 200:
                xml_text = rr.text
                rr.close()
                out.extend(_xml_urls(xml_text))
            else:
                rr.close()
        except Exception:
            pass

    return out


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
    Controlla solo il contesto locale del prezzo.

    Non usiamo tutto il parent tree indiscriminatamente: sulla pagina reale
    il blocco coupon e i prezzi delle varianti possono stare nello stesso
    contenitore generale. Un controllo troppo largo farebbe scartare anche
    i prezzi normali.
    """
    current = node

    for _ in range(3):
        if current is None:
            break

        text = current.get_text(" ", strip=True)
        if _has_coupon_indicator(text):
            # Se il contenitore è enorme, il termine coupon può appartenere
            # a un'altra sezione della pagina: in quel caso non lo consideriamo.
            if len(text) <= 500:
                return True

        if current is stop_node:
            break
        current = current.parent

    return False


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
    r = SESSION.get(url, headers=HEADERS, timeout=4)

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


def search(query):
    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP:", e)
        return []

    candidates = []

    for url in urls:
        if re.search(r"_z\d+/?$", url) and _all_tokens_match(url, query):
            candidates.append(url)

    results = []
    seen = set()

    try:
        for url in candidates[:6]:
            try:
                items = _extract_product(url, query)
            except Exception as e:
                print("ERRORE PRODOTTO PARFUMZENTRUM:", repr(e))
                items = []

            for item in items:
                if not item:
                    continue

                key = (
                    item["name"].lower(),
                    item["url"],
                    item.get("size_ml", ""),
                )

                if key not in seen:
                    seen.add(key)
                    results.append(item)
    finally:
        SESSION.close()

    return results


if __name__ == "__main__":
    results = search("Rasasi Hawas For Him")
    print("RISULTATI:", len(results))

    for item in results[:10]:
        print(item)

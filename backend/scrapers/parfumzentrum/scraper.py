import re
import gzip
import time
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# Evita di riscaricare tutte le sitemap ad ogni ricerca.
_SITEMAP_CACHE = None
_SITEMAP_CACHE_TIME = 0
SITEMAP_CACHE_SECONDS = 60 * 60

# Limiti pensati per non far scattare il timeout del backend.
MAX_CANDIDATES = 24
MAX_WORKERS = 8
REQUEST_TIMEOUT = 8


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(text or ""))
        if len(x) > 1
    ]


def _normal(text):
    return " ".join(_tokens(text))


def _all_tokens_match(text, query):
    hay = set(_tokens(text))
    return all(t in hay for t in _tokens(query))


def _xml_urls(content):
    # Supporta sia XML normale sia sitemap .xml.gz.
    if isinstance(content, bytes):
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        root = ET.fromstring(content)
    else:
        root = ET.fromstring(content.encode("utf-8"))

    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _download_xml(url):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return _xml_urls(r.content)


def _get_sitemap_urls():
    global _SITEMAP_CACHE, _SITEMAP_CACHE_TIME

    now = time.time()
    if _SITEMAP_CACHE is not None and now - _SITEMAP_CACHE_TIME < SITEMAP_CACHE_SECONDS:
        return _SITEMAP_CACHE

    urls = _download_xml(SITEMAP_URL)

    child_maps = [
        u for u in urls
        if "sitemap" in u.lower()
        and u.lower().endswith((".xml", ".xml.gz"))
    ]

    if child_maps:
        out = []
        # Anche le sitemap figlie vengono scaricate in parallelo.
        with ThreadPoolExecutor(max_workers=min(6, len(child_maps))) as ex:
            futures = [ex.submit(_download_xml, sm) for sm in child_maps]
            for f in as_completed(futures):
                try:
                    out.extend(f.result())
                except Exception:
                    pass
        urls = out

    _SITEMAP_CACHE = urls
    _SITEMAP_CACHE_TIME = now
    return urls


def _candidate_score(url, query):
    """Mette prima gli URL che assomigliano di più alla query."""
    q = _tokens(query)
    u = _tokens(url)

    score = 0
    for t in q:
        if t in u:
            score += 10

    # Bonus se le parole compaiono nello stesso ordine.
    nq = _normal(query)
    nu = _normal(url)
    if nq and nq in nu:
        score += 30

    # URL più corti tendono ad essere più specifici/puliti.
    score -= len(url) / 1000
    return score


def _extract_volume_from_name(name):
    """Restituisce il formato in ml presente nel nome del prodotto."""
    m = re.search(r"\b(\d{1,4})\s*ml\b", name or "", re.I)
    return int(m.group(1)) if m else None


def _parse_price(value):
    """Converte un prezzo testuale tedesco in formato ScentHunter."""
    if value is None:
        return None
    m = re.search(r"(\d{1,5}[.,]\d{2})", str(value))
    if not m:
        return None
    return m.group(1).replace(".", ",") + "€"


def _extract_price_for_volume(soup, name, product_text):
    """
    Estrae il prezzo della variante realmente rappresentata dalla pagina.

    Parfum-Zentrum mostra spesso nella stessa pagina una riga del tipo:
        100 ml 54,03 €   50 ml 37,89 €   30 ml 31,86 €
    seguita dal prezzo della variante selezionata.

    Non bisogna quindi prendere il primo numero seguito da €.
    Cerchiamo prima la coppia FORMATO -> PREZZO corrispondente all'h1.
    """
    volume = _extract_volume_from_name(name)

    # 1) Prima scelta: coppia esplicita "50 ml 37,89 €" nel contenuto
    #    vicino al prodotto. Questo evita completamente il prezzo barrato,
    #    il prezzo consigliato e il prezzo al litro.
    if volume is not None:
        volume_patterns = [
            rf"\b{volume}\s*ml\b\s*[:\-]?\s*(\d{{1,5}}[.,]\d{{2}})\s*€",
            rf"\b{volume}\s*ml\b[^€]{{0,80}}?(\d{{1,5}}[.,]\d{{2}})\s*€",
        ]
        for pattern in volume_patterns:
            m = re.search(pattern, product_text, re.I | re.S)
            if m:
                return _parse_price(m.group(1))

    # 2) JSON-LD: quando il sito espone un'offerta strutturata, preferirla.
    #    Scartiamo le offerte senza prezzo e, se possibile, quelle che non
    #    corrispondono al formato della pagina.
    offers = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            import json
            data = json.loads(raw)
        except Exception:
            continue

        nodes = data if isinstance(data, list) else [data]
        expanded = []
        for node in nodes:
            if isinstance(node, dict) and "@graph" in node and isinstance(node["@graph"], list):
                expanded.extend(node["@graph"])
            else:
                expanded.append(node)

        for node in expanded:
            if not isinstance(node, dict):
                continue
            offer = node.get("offers")
            if isinstance(offer, dict):
                offers.append(offer)
            elif isinstance(offer, list):
                offers.extend(x for x in offer if isinstance(x, dict))

    for offer in offers:
        price = _parse_price(offer.get("price"))
        if price:
            return price

    # 3) Fallback sicuro: prezzo di vendita esplicito con IVA.
    patterns = [
        r"(\d{1,5}[.,]\d{2})\s*€\s*inkl\.",
        r"Versandbereit\s*(\d{1,5}[.,]\d{2})\s*€",
    ]
    for pattern in patterns:
        m = re.search(pattern, product_text, re.I | re.S)
        if m:
            return _parse_price(m.group(1))

    return None


def _extract_product(url, query):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)
    if not _all_tokens_match(name, query):
        return None

    # Costruiamo il contesto del prodotto partendo dall'h1, senza usare
    # l'intera pagina: così non catturiamo prezzi di prodotti correlati.
    chunks = []
    node = h1
    for _ in range(8):
        if not node:
            break
        txt = node.get_text(" ", strip=True)
        if txt:
            chunks.append(txt)
        node = node.parent

    product_text = min(
        (x for x in chunks if len(x) >= len(name) and "€" in x),
        key=len,
        default="",
    )

    unavailable_phrases = (
        "leider nicht lieferbar",
        "nicht lieferbar",
        "nicht vorrätig",
        "ausverkauft",
    )
    page_near_h1 = " ".join(chunks[:5]).lower()
    if any(x in page_near_h1 for x in unavailable_phrases):
        return None

    price = _extract_price_for_volume(
        soup,
        name,
        product_text,
    )

    if not price:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
    }

def search(query):
    query = (query or "").strip()
    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
    except Exception as e:
        print("ERRORE SITEMAP PARFUMZENTRUM:", repr(e))
        return []

    # Prima filtriamo usando SOLO la sitemap: operazione velocissima.
    candidates = [
        url for url in urls
        if re.search(r"_z\d+/?$", url)
        and _all_tokens_match(url, query)
    ]

    # Le ricerche generiche (es. "Versace pour femme") possono produrre
    # molti URL. Li ordiniamo e ne controlliamo un numero limitato.
    candidates.sort(key=lambda u: _candidate_score(u, query), reverse=True)
    candidates = candidates[:MAX_CANDIDATES]

    if not candidates:
        return []

    results = []
    seen = set()

    # Punto chiave: NON apriamo più le pagine una alla volta.
    # Le richieste vengono eseguite in parallelo, riducendo molto il tempo.
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(candidates))) as ex:
        future_to_url = {
            ex.submit(_extract_product, url, query): url
            for url in candidates
        }

        for future in as_completed(future_to_url):
            try:
                item = future.result()
            except Exception as e:
                print("ERRORE PRODOTTO PARFUMZENTRUM:", future_to_url[future], repr(e))
                continue

            if item:
                key = (item["name"].lower(), item["price"])
                if key not in seen:
                    seen.add(key)
                    results.append(item)

    results.sort(key=lambda x: x["name"].lower())
    return results


if __name__ == "__main__":
    # Caso che prima faceva scattare "parfumzentrum non ha risposto".
    test_query = "Versace pour femme"
    start = time.time()
    results = search(test_query)

    print("QUERY:", test_query)
    print("TEMPO:", round(time.time() - start, 2), "secondi")
    print("RISULTATI:", len(results))
    for item in results:
        print(item)

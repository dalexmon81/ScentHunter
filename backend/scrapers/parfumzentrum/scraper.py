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
MAX_CANDIDATES = 32
MAX_WORKERS = 8
REQUEST_TIMEOUT = 12


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


def _get_sitemap_urls(force_refresh=False):
    global _SITEMAP_CACHE, _SITEMAP_CACHE_TIME

    now = time.time()
    if (
        not force_refresh
        and _SITEMAP_CACHE is not None
        and now - _SITEMAP_CACHE_TIME < SITEMAP_CACHE_SECONDS
    ):
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


def _relaxed_candidate_score(url, query):
    """Punteggio per il fallback quando lo slug URL non contiene tutti i token."""
    q = _tokens(query)
    u = set(_tokens(url))

    matched = sum(1 for token in q if token in u)
    if matched == 0:
        return -1

    score = matched * 10
    nq = _normal(query)
    nu = _normal(url)
    if nq and nq in nu:
        score += 30

    # Se il brand/nome compare quasi tutto nello slug, preferiscilo.
    score += max(0, matched - 1) * 2
    score -= len(url) / 1000
    return score


def _extract_product(url, query):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    # Il controllo definitivo viene fatto sul nome reale del prodotto.
    if not _all_tokens_match(name, query):
        return None

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
        default=""
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

    patterns = [
        r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.",
        r"Versandbereit\s*(\d{1,4}[.,]\d{2})\s*€",
        r"(\d{1,4}[.,]\d{2})\s*€",
    ]

    price = ""
    for pattern in patterns:
        m = re.search(pattern, product_text, re.I)
        if m:
            price = m.group(1).replace(".", ",") + "€"
            break

    if not price:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
    }


def _build_candidates(urls, query):
    """Costruisce candidati prima con match completo, poi con match rilassato."""
    product_urls = [
        url for url in urls
        if re.search(r"_z\d+/?$", url)
    ]

    strict = [
        url for url in product_urls
        if _all_tokens_match(url, query)
    ]
    strict.sort(key=lambda u: _candidate_score(u, query), reverse=True)

    if strict:
        # Manteniamo comunque un piccolo fallback rilassato: alcuni slug del sito
        # possono omettere una parola presente nel nome visualizzato.
        relaxed = [
            url for url in product_urls
            if url not in strict
            and _relaxed_candidate_score(url, query) >= 20
        ]
        relaxed.sort(
            key=lambda u: _relaxed_candidate_score(u, query),
            reverse=True,
        )
        return (strict + relaxed)[:MAX_CANDIDATES]

    relaxed = [
        url for url in product_urls
        if _relaxed_candidate_score(url, query) >= 10
    ]
    relaxed.sort(
        key=lambda u: _relaxed_candidate_score(u, query),
        reverse=True,
    )
    return relaxed[:MAX_CANDIDATES]


def search(query):
    query = (query or "").strip()
    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
        candidates = _build_candidates(urls, query)

        # Se la sitemap in cache non contiene il prodotto, la ricarichiamo una
        # sola volta. Questo è importante per prodotti nuovi o appena modificati.
        if not candidates:
            print("PARFUMZENTRUM: nessun candidato dalla sitemap cache, refresh forzato")
            urls = _get_sitemap_urls(force_refresh=True)
            candidates = _build_candidates(urls, query)

    except Exception as e:
        print("ERRORE SITEMAP PARFUMZENTRUM:", repr(e))
        return []

    if not candidates:
        return []

    results = []
    seen = set()

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
                print(
                    "ERRORE PRODOTTO PARFUMZENTRUM:",
                    future_to_url[future],
                    repr(e),
                )
                continue

            if item:
                key = (item["name"].lower(), item["price"])
                if key not in seen:
                    seen.add(key)
                    results.append(item)

    results.sort(key=lambda x: x["name"].lower())
    return results


if __name__ == "__main__":
    test_query = "Khadlaj Onyx Gold"
    start = time.time()
    results = search(test_query)

    print("QUERY:", test_query)
    print("TEMPO:", round(time.time() - start, 2), "secondi")
    print("RISULTATI:", len(results))
    for item in results:
        print(item)

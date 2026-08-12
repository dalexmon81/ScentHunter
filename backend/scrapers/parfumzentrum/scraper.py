import re
import gzip
import time
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote, urljoin, urlparse
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
FALLBACK_MAX_PAGES = 4


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

    nq = _normal(query)
    nu = _normal(url)
    if nq and nq in nu:
        score += 30

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

    score += max(0, matched - 1) * 2
    score -= len(url) / 1000
    return score


def _is_product_url(url):
    """Riconosce gli URL prodotto senza dipendere dal solo suffisso _z123456."""
    path = urlparse(url).path.lower()
    if not path.startswith("/"):
        return False
    if any(x in path for x in ("/sitemap", "/suchen", "/marke/", "/f/", "/angebote/", "/artikel/")):
        return False
    return bool(re.search(r"(?:_z\d+|[-_]z\d+)(?:/)?$", path)) or "_z" in path


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
    product_urls = [url for url in urls if _is_product_url(url)]

    strict = [
        url for url in product_urls
        if _all_tokens_match(url, query)
    ]
    strict.sort(key=lambda u: _candidate_score(u, query), reverse=True)

    if strict:
        relaxed = [
            url for url in product_urls
            if url not in strict
            and _relaxed_candidate_score(url, query) >= 20
        ]
        relaxed.sort(key=lambda u: _relaxed_candidate_score(u, query), reverse=True)
        return (strict + relaxed)[:MAX_CANDIDATES]

    relaxed = [
        url for url in product_urls
        if _relaxed_candidate_score(url, query) >= 10
    ]
    relaxed.sort(key=lambda u: _relaxed_candidate_score(u, query), reverse=True)
    return relaxed[:MAX_CANDIDATES]


def _fallback_category_urls(query):
    """Costruisce le principali pagine catalogo del brand indicato nella query."""
    tokens = _tokens(query)
    if not tokens:
        return []

    # Per i nomi composti più comuni manteniamo il brand completo; per gli altri
    # il primo token è normalmente il marchio (Khadlaj, Afnan, Armani, ecc.).
    brand_candidates = [tokens[0]]
    if len(tokens) >= 2 and tokens[0] in {"al", "j", "mancera", "maison"}:
        brand_candidates.insert(0, "-".join(tokens[:2]))

    urls = []
    for brand in brand_candidates:
        slug = re.sub(r"[^a-z0-9-]+", "-", brand.lower()).strip("-")
        if not slug:
            continue
        urls.extend([
            f"{BASE_URL}/{slug}_v1200/",
            f"{BASE_URL}/parfums/f/{slug}/",
            f"{BASE_URL}/oriental-court/f/{slug}/",
        ])

    # Evita richieste duplicate.
    return list(dict.fromkeys(urls))


def _fallback_links_from_page(page_url, query):
    """Estrae link prodotto dalla pagina catalogo e dalle sue prime pagine successive."""
    found = []
    visited_pages = set()
    queue = [page_url]

    while queue and len(visited_pages) < FALLBACK_MAX_PAGES:
        url = queue.pop(0)
        if url in visited_pages:
            continue
        visited_pages.add(url)

        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                continue
        except Exception as e:
            print("PARFUMZENTRUM: fallback page error", url, repr(e))
            continue

        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, a.get("href", "").strip())
            if not href.startswith(BASE_URL):
                continue

            text = " ".join(a.stripped_strings)
            combined = f"{text} {href}"
            if not _is_product_url(href):
                # Alcuni link prodotto possono non avere il suffisso perfetto:
                # il testo deve però contenere almeno due token della query.
                matched = sum(t in set(_tokens(combined)) for t in _tokens(query))
                if matched < min(2, len(_tokens(query))):
                    continue

            score = _candidate_score(combined, query)
            if score >= 15 or _all_tokens_match(combined, query):
                found.append((score, href))

        # Segui solo la paginazione della stessa sezione, senza esplorare tutto il sito.
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, a.get("href", "").strip())
            if href.startswith(page_url.rstrip("/") + "?") and "page=" in href.lower():
                if href not in visited_pages and href not in queue:
                    queue.append(href)

    # Prima i link più promettenti e poi deduplica.
    found.sort(key=lambda x: x[0], reverse=True)
    out = []
    seen = set()
    for _, href in found:
        if href not in seen:
            seen.add(href)
            out.append(href)
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def _fallback_candidates(query):
    """Fallback reale sul catalogo quando sitemap/cache non producono candidati."""
    all_links = []
    seen = set()

    for page_url in _fallback_category_urls(query):
        links = _fallback_links_from_page(page_url, query)
        for link in links:
            if link not in seen:
                seen.add(link)
                all_links.append(link)
        if all_links:
            # Una pagina catalogo che ha già prodotto candidati è sufficiente.
            break

    all_links.sort(key=lambda u: _candidate_score(u, query), reverse=True)
    return all_links[:MAX_CANDIDATES]


def search(query):
    query = (query or "").strip()
    if not query:
        return []

    candidates = []

    try:
        urls = _get_sitemap_urls()
        candidates = _build_candidates(urls, query)

        if not candidates:
            print("PARFUMZENTRUM: nessun candidato dalla sitemap cache, refresh forzato")
            urls = _get_sitemap_urls(force_refresh=True)
            candidates = _build_candidates(urls, query)

    except Exception as e:
        print("ERRORE SITEMAP PARFUMZENTRUM:", repr(e))

    # Nuova strada: se la sitemap non espone il prodotto, interroghiamo il catalogo
    # del brand e prendiamo i link reali presenti nelle pagine, poi verifichiamo
    # ogni prodotto dalla pagina individuale.
    if not candidates:
        print("PARFUMZENTRUM: avvio fallback catalogo per", repr(query))
        candidates = _fallback_candidates(query)

    if not candidates:
        return []

    results = []
    seen = set()

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

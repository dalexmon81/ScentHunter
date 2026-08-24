import gzip
import re
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://www.parfum-zentrum.de"
SITEMAP_URL = BASE_URL + "/sitemap.xml"

SESSION = requests.Session()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Generic text / matching helpers
# ---------------------------------------------------------------------------


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(
            r"[A-Za-zÀ-ÿ0-9]+",
            unquote(str(text or "")),
        )
        if len(x) > 1
    ]


def _all_tokens_match(text, query):
    low = unquote(str(text or "")).lower().replace("-", " ")
    tokens = _tokens(query)
    return bool(tokens) and all(token in low for token in tokens)


def _xml_urls(xml_text):
    """Extract every <loc> from XML, including sitemap namespaces."""
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _decode_sitemap_content(response):
    """Return decoded sitemap XML, including .gz / gzip HTTP responses."""
    raw = response.content

    content_encoding = (response.headers.get("Content-Encoding") or "").lower()
    content_type = (response.headers.get("Content-Type") or "").lower()
    url = response.url.lower()

    is_gzip = (
        url.endswith(".gz")
        or "gzip" in content_encoding
        or "gzip" in content_type
        or raw[:2] == b"\x1f\x8b"
    )

    if is_gzip:
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError):
            # Some servers already transparently decode the body even though
            # the URL/content headers still advertise gzip.
            pass

    return raw.decode(
        response.encoding or "utf-8",
        errors="replace",
    )


# ---------------------------------------------------------------------------
# Sitemap discovery
# ---------------------------------------------------------------------------


def _fetch_sitemap(url):
    try:
        response = SESSION.get(
            url,
            headers=HEADERS,
            timeout=15,
        )

        if response.status_code != 200:
            response.close()
            return []

        text = _decode_sitemap_content(response)
        response.close()

        return _xml_urls(text)

    except Exception:
        return []


def _get_sitemap_urls():
    """Recursively walk sitemap indexes until actual URLs are reached.

    The previous implementation only handled one sitemap-index level and
    silently discarded compressed child maps. That can make an otherwise
    valid product disappear from discovery. This version follows sitemap
    indexes recursively and understands both .xml and .xml.gz maps.
    """
    first_level = _fetch_sitemap(SITEMAP_URL)

    if not first_level:
        return []

    pending = []
    seen_maps = set()
    output = []

    def enqueue(url):
        url = str(url or "").strip()
        if not url:
            return
        low = url.lower()
        if low.endswith((".xml", ".xml.gz")) or "sitemap" in low:
            if url not in seen_maps and url not in pending:
                pending.append(url)

    for url in first_level:
        enqueue(url)

    # If /sitemap.xml is itself a URL set rather than an index, preserve those
    # URLs instead of trying to classify them as child maps.
    if not pending:
        return first_level

    while pending:
        # Process a bounded batch in parallel. Failed maps are simply skipped;
        # successful maps remain available for the next recursive level.
        batch = []
        while pending and len(batch) < 12:
            url = pending.pop(0)
            if url in seen_maps:
                continue
            seen_maps.add(url)
            batch.append(url)

        if not batch:
            continue

        with ThreadPoolExecutor(
            max_workers=min(8, len(batch))
        ) as executor:
            futures = {
                executor.submit(_fetch_sitemap, url): url
                for url in batch
            }

            for future in as_completed(futures):
                try:
                    values = future.result() or []
                except Exception:
                    values = []

                for value in values:
                    value = str(value or "").strip()
                    if not value:
                        continue

                    low = value.lower()
                    if low.endswith((".xml", ".xml.gz")) or "sitemap" in low:
                        enqueue(value)
                    else:
                        output.append(value)

    return list(dict.fromkeys(output))


# ---------------------------------------------------------------------------
# Product extraction
# ---------------------------------------------------------------------------


def _extract_product(url, query):
    try:
        response = SESSION.get(
            url,
            headers=HEADERS,
            timeout=12,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        response.close()
        return None

    html = response.text
    response.close()

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")

    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _all_tokens_match(name, query):
        return None

    # Work only around the actual product heading, avoiding prices from
    # navigation/recommendations elsewhere on the page.
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
        (
            x for x in chunks
            if len(x) >= len(name) and "€" in x
        ),
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

    if any(
        phrase in page_near_h1
        for phrase in unavailable_phrases
    ):
        return None

    patterns = (
        r"(\d{1,4}[.,]\d{2})\s*€\s*inkl\.",
        r"Versandbereit\s*(\d{1,4}[.,]\d{2})\s*€",
        r"(\d{1,4}[.,]\d{2})\s*€",
    )

    price = ""

    for pattern in patterns:
        match = re.search(
            pattern,
            product_text,
            re.I,
        )

        if match:
            price = (
                match.group(1)
                .replace(".", ",")
                + "€"
            )
            break

    if not price:
        return None

    return {
        "store": "ParfumZentrum",
        "name": name,
        "price": price,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search(query):
    query = str(query or "").strip()

    if not query:
        return []

    try:
        urls = _get_sitemap_urls()
    except Exception as error:
        print("ERRORE SITEMAP:", error)
        return []

    candidates = []

    for url in urls:
        normalized = str(url or "").rstrip("/")

        if not re.search(
            r"_z\d+$",
            normalized,
            re.I,
        ):
            continue

        if _all_tokens_match(
            normalized,
            query,
        ):
            candidates.append(normalized)

    # Manteniamo tutti i candidati trovati. Il vecchio [:24] poteva troncare
    # proprio le varianti che servono a ScentHunter.
    query_tokens = set(_tokens(query))

    def candidate_score(url):
        path = unquote(url).lower().replace("-", " ")
        return sum(
            10 for token in query_tokens
            if token in path
        )

    candidates = sorted(
        set(candidates),
        key=candidate_score,
        reverse=True,
    )

    results = []
    seen = set()

    # Fetch concorrente dei candidati: discovery completa senza trasformare
    # l'aumento della copertura in un timeout seriale enorme.
    def fetch_one(url):
        try:
            return _extract_product(url, query)
        except Exception:
            return None

    with ThreadPoolExecutor(
        max_workers=min(8, max(1, len(candidates)))
    ) as executor:
        futures = [
            executor.submit(fetch_one, url)
            for url in candidates
        ]

        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception:
                item = None

            if not item:
                continue

            key = (
                item["name"].lower(),
                item["price"],
                item["url"].lower(),
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(item)

    # Restituiamo un ordine stabile, indipendente dal completamento dei thread.
    results.sort(
        key=lambda item: (
            item["name"].lower(),
            item["url"].lower(),
        )
    )

    return results


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]).strip()

    if query:
        results = search(query)
        print("RISULTATI:", len(results))

        for item in results:
            print(item)

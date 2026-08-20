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
    root = ET.fromstring(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if el.tag.endswith("loc") and el.text
    ]


def _get_sitemap_urls():
    response = SESSION.get(
        SITEMAP_URL,
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()

    urls = _xml_urls(response.text)
    response.close()

    child_maps = [
        url for url in urls
        if "sitemap" in url.lower()
        and url.lower().endswith((".xml", ".xml.gz"))
    ]

    if not child_maps:
        return urls

    def fetch_child(url):
        try:
            child = SESSION.get(
                url,
                headers=HEADERS,
                timeout=15,
            )
            if child.status_code != 200:
                child.close()
                return []

            data = _xml_urls(child.text)
            child.close()
            return data
        except Exception:
            return []

    output = []

    # Parallelizza i child sitemap: la discovery non deve consumare
    # il timeout globale solo perché i sitemap sono numerosi.
    with ThreadPoolExecutor(
        max_workers=min(8, max(1, len(child_maps)))
    ) as executor:
        futures = [
            executor.submit(fetch_child, sitemap)
            for sitemap in child_maps
        ]

        for future in as_completed(futures):
            try:
                output.extend(future.result() or [])
            except Exception:
                continue

    return output


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

    # Non limitiamo arbitrariamente la discovery a 6 URL:
    # prima vengono ordinati i candidati più pertinenti.
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

    for url in candidates[:24]:
        try:
            item = _extract_product(
                url,
                query,
            )
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

    return results


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]).strip()

    if query:
        results = search(query)
        print("RISULTATI:", len(results))

        for item in results:
            print(item)

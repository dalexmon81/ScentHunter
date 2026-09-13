from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"

NOTINO_HOSTS = {
    "notino.fr",
    "www.notino.fr",
}

BING_SEARCH_URL = "https://www.bing.com/search"
BING_RSS_URL = "https://www.bing.com/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Cache-Control": "no-cache",
}


# ============================================================
# GENERIC
# ============================================================

def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _query_words(query: str) -> List[str]:
    return [
        re.sub(r"[^a-z0-9àâäéèêëîïôöùûüÿç-]", "", word.lower())
        for word in query.split()
        if len(word.strip()) >= 2
    ]


def _price(text: str) -> str:
    if not text:
        return ""

    patterns = (
        r"(?:à\s+partir\s+de|a\s+partir\s+de|de|dès)\s+"
        r"(\d{1,4}(?:[.,]\d{2})?)\s*€",

        r"(\d{1,4}(?:[.,]\d{2}))\s*€",

        r"(\d{1,4})\s*€",
    )

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = match.group(1).replace(".", ",")

            if "," not in value:
                value += ",00"

            return f"{value}€"

    return ""


def _clean_title(title: str) -> str:
    title = _clean(title)

    title = re.sub(
        r"^(?:livraison\s+offerte\s+)?"
        r"(?:promo\s+|promotion\s+)?"
        r"(?:cadeaux?|cadeau)\s+offerts?\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"^(?:promo|promotion)\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"\s+\d[,.]\d\s*\(\s*\d+\s*\)"
        r"\s+(?:de\s+)?\d{1,4}[,.]\d{2}\s*€.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    title = re.sub(
        r"\s+(?:de\s+)?\d{1,4}[,.]\d{2}\s*€.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    return _clean(title)


# ============================================================
# NOTINO URL
# ============================================================

def _unwrap_bing_url(url: str) -> str:
    """
    Bing può restituire link diretti oppure link di tracking.

    Prova a recuperare il vero URL dal parametro u.
    """

    url = _clean(url)

    if not url:
        return ""

    if "notino.fr" in url.lower():
        return url

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        for key in ("u", "url", "r"):
            values = params.get(key)

            if not values:
                continue

            candidate = unquote(values[0])

            if "notino.fr" in candidate.lower():
                return candidate

    except Exception:
        pass

    return url


def _is_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.netloc.lower() not in NOTINO_HOSTS:
        return False

    path = parsed.path.lower()

    # Il formato moderno delle schede prodotto Notino.
    #
    # /french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/
    #
    if not re.search(r"/p-\d+/?$", path):
        return False

    blocked = (
        "/search",
        "/cart",
        "/wishlist",
        "/mynotino",
        "/livraison",
        "/avis/",
        "/contact",
        "/magazine",
    )

    if any(item in path for item in blocked):
        return False

    return True


# ============================================================
# PRODUCT FILTER
# ============================================================

def _single_perfume(title: str) -> bool:
    low = _clean(title).lower()

    blocked = (
        "coffret",
        "gift set",
        "set cadeau",
        "coffret cadeau",
        "miniature",
        "échantillon",
        "echantillon",
        "sample",
        "discovery set",
        "lot de ",
        "pack de ",
        "duo ",
        "trio ",
        "gel douche",
        "shower gel",
        "déodorant",
        "deodorant",
        "lotion corps",
        "body lotion",
        "crème corps",
        "creme corps",
        "body cream",
        "après-rasage",
        "apres-rasage",
        "after shave",
        "aftershave",
        "spray corps",
        "body spray",
        "brume",
        "hair mist",
        "shampooing",
        "shampoo",
        "conditioner",
    )

    return not any(item in low for item in blocked)


def _matches_query(title: str, snippet: str, query: str) -> bool:
    words = _query_words(query)

    if not words:
        return True

    text = f"{title} {snippet}".lower()

    matches = sum(1 for word in words if word and word in text)

    if len(words) == 1:
        return matches >= 1

    # Per "Liquid Brun" vogliamo almeno una delle parole.
    # Il nome completo viene comunque controllato dal titolo/snippet.
    return matches >= max(1, len(words) - 1)


# ============================================================
# RESULT
# ============================================================

def _make_result(
    title: str,
    snippet: str,
    url: str,
    query: str,
) -> Dict[str, Any] | None:

    url = _unwrap_bing_url(url)

    if not _is_product_url(url):
        return None

    title = _clean_title(title)
    snippet = _clean(snippet)

    if not _matches_query(title, snippet, query):
        return None

    if not _single_perfume(title):
        return None

    price = _price(snippet)

    if not price:
        price = _price(title)

    if not price:
        return None

    if len(title) < 3:
        title = _clean(query)

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": url,
    }


# ============================================================
# BING HTML
# ============================================================

def _bing_html(query: str) -> List[Dict[str, Any]]:
    search_query = f'site:notino.fr "{query}"'

    try:
        response = requests.get(
            BING_SEARCH_URL,
            params={
                "q": search_query,
                "count": "20",
            },
            headers=HEADERS,
            timeout=(3.0, 8.0),
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        print(f"NOTINO BING HTML ERROR: {exc}")
        return []

    html = response.text

    soup = BeautifulSoup(html, "html.parser")

    results: List[Dict[str, Any]] = []
    seen = set()

    # --------------------------------------------------------
    # Metodo storico Bing
    # --------------------------------------------------------

    nodes = soup.select("li.b_algo")

    # --------------------------------------------------------
    # Fallback: Bing può cambiare markup.
    # --------------------------------------------------------

    if not nodes:
        nodes = soup.select("li[class*='b_algo']")

    if not nodes:
        # Cerca direttamente i link che contengono Notino.
        candidates = []

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")

            if "notino.fr" in href.lower():
                candidates.append(anchor)

        for anchor in candidates:

            href = _unwrap_bing_url(anchor.get("href", ""))

            if not _is_product_url(href):
                continue

            title = _clean_title(
                anchor.get_text(" ", strip=True)
            )

            parent = anchor

            for _ in range(5):
                if parent.parent is None:
                    break

                parent = parent.parent

                text = _clean(
                    parent.get_text(" ", strip=True)
                )

                if "€" in text:
                    break

            snippet = _clean(
                parent.get_text(" ", strip=True)
            )

            result = _make_result(
                title,
                snippet,
                href,
                query,
            )

            if result is None:
                continue

            if result["url"] in seen:
                continue

            seen.add(result["url"])
            results.append(result)

            if len(results) >= 12:
                break

        if results:
            return results

    # --------------------------------------------------------
    # Parsing normale b_algo
    # --------------------------------------------------------

    for node in nodes:

        anchor = node.select_one("h2 a")

        if anchor is None:
            anchor = node.select_one("a[href]")

        if anchor is None:
            continue

        href = anchor.get("href", "")

        href = _unwrap_bing_url(href)

        if not _is_product_url(href):
            continue

        title = _clean_title(
            anchor.get_text(" ", strip=True)
        )

        snippet_node = (
            node.select_one(".b_caption p")
            or node.select_one(".b_caption")
            or node
        )

        snippet = _clean(
            snippet_node.get_text(" ", strip=True)
        )

        result = _make_result(
            title,
            snippet,
            href,
            query,
        )

        if result is None:
            continue

        if result["url"] in seen:
            continue

        seen.add(result["url"])
        results.append(result)

        if len(results) >= 12:
            break

    return results


# ============================================================
# BING RSS
# ============================================================

def _bing_rss(query: str) -> List[Dict[str, Any]]:
    """
    Secondo livello di fallback.

    Se Bing HTML restituisce una pagina diversa dal markup
    storico, utilizziamo il feed RSS di Bing.
    """

    search_query = f'site:notino.fr "{query}"'

    try:
        response = requests.get(
            BING_RSS_URL,
            params={
                "q": search_query,
                "format": "rss",
            },
            headers={
                **HEADERS,
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
            timeout=(3.0, 8.0),
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        print(f"NOTINO BING RSS ERROR: {exc}")
        return []

    try:
        root = ET.fromstring(response.text)

    except ET.ParseError as exc:
        print(f"NOTINO BING RSS PARSE ERROR: {exc}")
        return []

    results: List[Dict[str, Any]] = []
    seen = set()

    for item in root.findall(".//item"):

        title_node = item.find("title")
        link_node = item.find("link")
        description_node = item.find("description")

        if title_node is None or link_node is None:
            continue

        title = _clean(
            title_node.text or ""
        )

        url = _clean(
            link_node.text or ""
        )

        snippet = ""

        if description_node is not None:
            snippet = _clean(
                description_node.text or ""
            )

        result = _make_result(
            title,
            snippet,
            url,
            query,
        )

        if result is None:
            continue

        if result["url"] in seen:
            continue

        seen.add(result["url"])
        results.append(result)

        if len(results) >= 12:
            break

    return results


# ============================================================
# BING MASTER
# ============================================================

def _bing(query: str) -> List[Dict[str, Any]]:
    """
    Discovery Notino tramite Bing.

    NON contatta Notino.

    Ordine:
      1. Bing HTML
      2. Bing RSS
    """

    query = _clean(query)

    if not query:
        return []

    results: List[Dict[str, Any]] = []
    seen = set()

    # --------------------------------------------------------
    # Query principali
    # --------------------------------------------------------

    queries = [
        query,
        f"{query} French Avenue",
    ]

    for current_query in queries:

        found = _bing_html(current_query)

        for result in found:

            url = result.get("url", "")

            if not url or url in seen:
                continue

            seen.add(url)
            results.append(result)

        if len(results) >= 12:
            return results

    # --------------------------------------------------------
    # RSS fallback
    # --------------------------------------------------------

    for current_query in queries:

        found = _bing_rss(current_query)

        for result in found:

            url = result.get("url", "")

            if not url or url in seen:
                continue

            seen.add(url)
            results.append(result)

        if len(results) >= 12:
            break

    return results[:12]


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def search(query: str) -> List[Dict[str, Any]]:
    """
    Entry point usato da ScentHunter.

    IMPORTANTE:
    nessuna richiesta diretta a Notino.

    Il 403 di Render viene quindi completamente evitato.
    """

    query = _clean(query)

    if not query:
        return []

    return _bing(query)


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":

    query = "Liquid Brun"

    results = search(query)

    print()
    print("=" * 70)
    print(f"NOTINO TEST: {query}")
    print(f"RISULTATI: {len(results)}")
    print("=" * 70)

    for result in results:
        print(result)

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.notino.fr"
TRANSLATE_BASE = "https://www-notino-fr.translate.goog"
TIMEOUT = 25

log = logging.getLogger("scenthunter.notino")
if not log.handlers:
    logging.basicConfig(level=logging.INFO)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRODUCT_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\"'<>\s]+/p-\d+/?",
    re.I,
)
REL_PRODUCT_RE = re.compile(
    r"(?:href=[\"']|https?://[^\"']*)"
    r"([^\"'<>\s]+/p-\d+/?)(?:[?#][^\"'<>\s]*)?",
    re.I,
)


def _translate_url(notino_url: str) -> str:
    parsed = notino_url.split("://", 1)[-1]
    if parsed.startswith("www.notino.fr"):
        path = parsed[len("www.notino.fr"):]
    elif parsed.startswith("notino.fr"):
        path = parsed[len("notino.fr"):]
    else:
        path = "/" + parsed.split("/", 1)[-1]

    return (
        TRANSLATE_BASE
        + path
        + ("&" if "?" in path else "?")
        + "_x_tr_sl=fr&_x_tr_tl=en&_x_tr_hl=en"
    )


def _get(url: str) -> requests.Response:
    log.info("NOTINO GET %s", url)

    # Primary route: Google Translate fetches the origin server-side.
    proxy_url = _translate_url(url)
    r = requests.get(
        proxy_url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    log.info(
        "NOTINO PROXY status=%s bytes=%s final=%s",
        r.status_code,
        len(r.content),
        r.url,
    )

    if r.status_code >= 400:
        raise requests.HTTPError(
            f"proxy HTTP {r.status_code} for {url} via {proxy_url}",
            response=r,
        )

    return r


def _extract_product_urls(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/p-" not in href.lower():
            continue

        # Translate pages may rewrite links back through translate.goog.
        if "notino.fr/" in href.lower():
            m = re.search(
                r"(https?://(?:www\.)?notino\.fr/[^?#\"'<>\s]+/p-\d+/?",
                href,
                re.I,
            )
            if m:
                href = m.group(1)
            else:
                continue
        elif href.startswith("/"):
            href = urljoin(BASE_URL, href)
        else:
            continue

        href = href.rstrip(".,;)")
        if href not in found:
            found.append(href)

    # Fallback regex in case the HTML contains escaped/embedded URLs.
    for m in PRODUCT_RE.findall(html or ""):
        u = m.rstrip(".,;)")
        if u not in found:
            found.append(u)

    return found


def _parse_price(text: str) -> float | None:
    patterns = [
        r"(\d{1,4}(?:[.,]\d{1,2})?)\s*€",
        r"€\s*(\d{1,4}(?:[.,]\d{1,2})?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return float(m.group(1).replace(".", "").replace(",", "."))
            except ValueError:
                pass
    return None


def _parse_product(url: str) -> Dict[str, Any] | None:
    try:
        r = _get(url)
    except Exception as exc:
        log.warning("NOTINO PRODUCT FAILED %s: %s", url, exc)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(" ", strip=True)

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)

    if not title:
        return None

    # Prefer the product name around the H1; strip common suffixes.
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"\s*\|\s*Notino.*$", "", title, flags=re.I).strip()

    price_num = _parse_price(text)

    size_ml = None
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\s*ml\b", text, re.I)
    if m:
        try:
            size_ml = float(m.group(1).replace(",", "."))
        except ValueError:
            pass

    lower = text.lower()
    unavailable = any(
        phrase in lower
        for phrase in (
            "rupture de stock",
            "indisponible",
            "épuisé",
            "out of stock",
            "sold out",
        )
    )

    return {
        "store": "notino",
        "shop": "Notino",
        "brand": "French Avenue" if "french avenue" in lower else "",
        "name": title,
        "price": price_num,
        "price_num": price_num,
        "size_ml": size_ml,
        "url": url,
        "available": not unavailable,
        "availability": "En stock" if not unavailable else "Rupture de stock",
    }


def search(query: str) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []

    search_url = f"{BASE_URL}/search.asp?exps={quote_plus(query)}"
    log.info("NOTINO SEARCH %r", query)

    response = _get(search_url)
    urls = _extract_product_urls(response.text)

    log.info("NOTINO SEARCH FOUND %d PRODUCT URLS", len(urls))

    # Only products belonging to the requested Notino result page.
    urls = urls[:12]

    if not urls:
        # The translated HTML can expose the exact Liquid Brun product links
        # as text even when anchor extraction is different.
        for match in re.findall(
            r"https?://(?:www\.)?notino\.fr/[^\"'<>\s]+/p-\d+/?",
            response.text,
            re.I,
        ):
            if match not in urls:
                urls.append(match)
            if len(urls) >= 12:
                break

    if not urls:
        log.warning("NOTINO SEARCH EMPTY: no product URLs")
        return []

    results: List[Dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=min(4, len(urls))) as executor:
        futures = {executor.submit(_parse_product, u): u for u in urls}
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)

    results.sort(
        key=lambda x: (
            not bool(x.get("available")),
            x.get("price_num") is None,
            x.get("price_num") or 0,
        )
    )

    log.info("NOTINO SEARCH DONE %r -> %d RESULTS", query, len(results))
    return results

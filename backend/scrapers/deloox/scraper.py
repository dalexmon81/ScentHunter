import json
import re
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.com"
SEARCH_URL = f"{BASE_URL}/search.html?q={{query}}"
TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9,it;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}

PRICE_RE = re.compile(r"(\d{1,4}[.,]\d{2})")


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize(value: str) -> str:
    value = _clean(value).lower()
    value = re.sub(r"[^\w\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _score_name_against_query(name: str, query: str) -> int:
    name_n = _normalize(name)
    query_n = _normalize(query)

    if not name_n or not query_n:
        return 0

    score = 0
    tokens = [t for t in query_n.split() if len(t) > 1]

    for token in tokens:
        if token in name_n:
            score += 10

    if query_n in name_n:
        score += 50

    return score


def _format_price(value) -> Optional[str]:
    if value is None:
        return None

    text = _clean(str(value)).replace("€", "")
    m = PRICE_RE.search(text)
    if not m:
        return None

    price = m.group(1).replace(".", ",")
    return f"{price} €"


def _is_unavailable(text: str) -> bool:
    text_n = _normalize(text)
    negative_markers = [
        "out of stock",
        "sold out",
        "not available",
        "temporarily unavailable",
        "niet op voorraad",
        "non disponibile",
        "esaurito",
    ]
    return any(marker in text_n for marker in negative_markers)


def _extract_url_from_node(node) -> str:
    link = node.find("a", href=True)
    if not link:
        return ""

    href = _clean(link.get("href", ""))
    if not href or href.startswith("#"):
        return ""

    return urljoin(BASE_URL, href.split("?")[0])


def _extract_name_from_node(node) -> str:
    selectors = [
        "[class*='name']",
        "[class*='title']",
        "h2",
        "h3",
        "h4",
        "a[title]",
    ]

    for sel in selectors:
        found = node.select_one(sel)
        if found:
            text = found.get("title") or found.get_text(" ", strip=True)
            text = _clean(text)
            if len(text) >= 3:
                return text

    link = node.find("a", href=True)
    if link:
        title = _clean(link.get("title", ""))
        if title:
            return title
        text = _clean(link.get_text(" ", strip=True))
        if text:
            return text

    return ""


def _extract_price_from_text(text: str) -> Optional[str]:
    m = PRICE_RE.search(_clean(text))
    if not m:
        return None
    return f"{m.group(1).replace('.', ',')} €"


def _add_result(
    results: List[Dict[str, str]],
    seen: set,
    query: str,
    name: str,
    price,
    url: str,
    raw_text: str = "",
) -> None:
    name = _clean(name)
    final_price = _format_price(price) if not isinstance(price, str) else _extract_price_from_text(price)
    url = _clean(url)

    if not name or not final_price or not url:
        return

    score = _score_name_against_query(name, query)
    if score <= 0:
        return

    unavailable = _is_unavailable(raw_text or name)
    key = url.split("?")[0]

    if key in seen:
        return

    seen.add(key)
    results.append(
        {
            "store": STORE,
            "name": name,
            "price": final_price,
            "url": url,
            "_score": score,
            "_unavailable": unavailable,
        }
    )


def _parse_data_drs_article(soup: BeautifulSoup, query: str, results: List[Dict[str, str]], seen: set) -> None:
    for node in soup.select("[data-drs-article]"):
        raw = node.get("data-drs-article", "").strip()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        name = data.get("name", "")
        price = data.get("price")
        url = _extract_url_from_node(node)
        if not url:
            continue

        _add_result(
            results=results,
            seen=seen,
            query=query,
            name=name,
            price=price,
            url=url,
            raw_text=json.dumps(data, ensure_ascii=False),
        )


def _parse_jsonld(soup: BeautifulSoup, query: str, results: List[Dict[str, str]], seen: set) -> None:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        raw = raw.strip()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            if "@graph" in item:
                stack.append(item["@graph"])
            if "itemListElement" in item:
                stack.append(item["itemListElement"])
            if "item" in item and isinstance(item["item"], (dict, list)):
                stack.append(item["item"])

            typ = item.get("@type")
            is_product = "Product" in typ if isinstance(typ, list) else typ == "Product"
            if not is_product:
                continue

            name = item.get("name", "")
            url = item.get("url", "")
            offers = item.get("offers", {})

            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            price = offers.get("price") if isinstance(offers, dict) else None
            availability = offers.get("availability", "") if isinstance(offers, dict) else ""

            _add_result(
                results=results,
                seen=seen,
                query=query,
                name=name,
                price=price,
                url=url,
                raw_text=f"{name} {availability}",
            )


def _parse_html_cards(soup: BeautifulSoup, query: str, results: List[Dict[str, str]], seen: set) -> None:
    selectors = [
        "[data-product-id]",
        "[data-product]",
        ".product",
        ".product-item",
        ".product-card",
        ".product-tile",
        "article",
        "li",
    ]

    nodes = []
    for selector in selectors:
        found = soup.select(selector)
        if found:
            nodes = found
            break

    for node in nodes:
        text = _clean(node.get_text(" ", strip=True))
        price = _extract_price_from_text(text)
        if not price:
            continue

        url = _extract_url_from_node(node)
        name = _extract_name_from_node(node)

        _add_result(
            results=results,
            seen=seen,
            query=query,
            name=name,
            price=price,
            url=url,
            raw_text=text,
        )


def _fetch_search_page(session: requests.Session, query: str) -> Optional[str]:
    try:
        url = SEARCH_URL.format(query=quote_plus(query))
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return None


def search(query: str) -> List[Dict[str, str]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    html_text = _fetch_search_page(session, query)
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    results: List[Dict[str, str]] = []
    seen = set()

    _parse_data_drs_article(soup, query, results, seen)
    _parse_jsonld(soup, query, results, seen)
    _parse_html_cards(soup, query, results, seen)

    available = [r for r in results if not r["_unavailable"]]
    final_results = available if available else results
    final_results.sort(key=lambda x: (-x["_score"], x["name"]))

    return [
        {
            "store": r["store"],
            "name": r["name"],
            "price": r["price"],
            "url": r["url"],
        }
        for r in final_results
    ]


if __name__ == "__main__":
    test_query = "Rasasi Hawas Ice"
    found = search(test_query)

    print(f"QUERY: {test_query}")
    print(f"RISULTATI: {len(found)}")
    for item in found:
        print(item)

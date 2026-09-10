from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def iter_json_nodes(payload: Any) -> Iterator[Any]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from iter_json_nodes(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from iter_json_nodes(value)


def extract_json_ld_blocks(html: str) -> List[Any]:
    soup = BeautifulSoup(html or "", "html.parser")
    payloads: List[Any] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payloads.append(json.loads(raw))
        except Exception:
            continue
    return payloads


def extract_json_ld_products(
    html: str,
    *,
    include_offer_nodes: bool = False,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for payload in extract_json_ld_blocks(html):
        for node in iter_json_nodes(payload):
            if not isinstance(node, dict):
                continue
            node_type = node.get("@type") or node.get("type")
            is_product = node_type == "Product" or (
                isinstance(node_type, list) and "Product" in node_type
            )
            if is_product or (include_offer_nodes and node.get("offers")):
                records.append(node)
    return records


def normalize_product_url(
    base_url: str,
    raw_url: Any,
    *,
    url_normalizer: Optional[Callable[[str], str]] = None,
) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""
    absolute = urljoin(base_url, value).split("?")[0].split("#")[0].rstrip("/")
    return url_normalizer(absolute) if callable(url_normalizer) else absolute


def discover_shopify_product_urls(
    session: Any,
    *,
    base_url: str,
    request_query: str,
    query_matcher: Callable[[str, str], bool],
    headers: Dict[str, str],
    timeout: float,
    limit: int = 8,
    match_query: Optional[str] = None,
    search_json_limit: int = 12,
    suggest_limit: int = 12,
    unavailable_products: str = "show",
    search_paths: Sequence[str] = ("/search",),
    allow_search_json: bool = True,
    allow_embedded_html_urls: bool = False,
    anchor_context_builder: Optional[Callable[[Any, str], Iterable[str]]] = None,
    url_normalizer: Optional[Callable[[str], str]] = None,
) -> List[str]:
    request_query = str(request_query or "").strip()
    target_query = str(match_query or request_query).strip()
    if not request_query or not target_query:
        return []

    urls: List[str] = []
    seen = set()

    def add(raw_url: Any, *contexts: Any) -> None:
        url = normalize_product_url(base_url, raw_url, url_normalizer=url_normalizer)
        if not url or "/products/" not in url:
            return
        if url in seen:
            return
        haystack = " ".join(str(value or "") for value in contexts if value not in (None, ""))
        if not query_matcher(haystack or url, target_query):
            return
        seen.add(url)
        urls.append(url)

    def iter_json_products(data: Any) -> Iterator[Dict[str, Any]]:
        for node in iter_json_nodes(data):
            if isinstance(node, dict):
                yield node

    def add_from_json_payload(data: Any) -> None:
        for node in iter_json_products(data):
            title = node.get("title") or node.get("name") or node.get("product_title") or ""
            vendor = node.get("vendor") or node.get("brand") or ""
            handle = node.get("handle") or ""
            product_url = node.get("url") or node.get("product_url") or ""
            if not product_url and handle:
                product_url = f"/products/{handle}"
            if product_url:
                add(product_url, title, vendor, handle, product_url)
                if len(urls) >= limit:
                    return

    def default_anchor_context(anchor: Any, url: str) -> List[str]:
        contexts = [
            anchor.get("title") or "",
            anchor.get("aria-label") or "",
            anchor.get_text(" ", strip=True) or "",
            url.replace("/products/", " ").replace("-", " "),
        ]
        for img in anchor.find_all("img", limit=4):
            contexts.append(img.get("alt") or "")
        return contexts

    def add_from_html(html: str) -> None:
        soup = BeautifulSoup(html or "", "html.parser")
        for anchor in soup.select('a[href*="/products/"]'):
            href = anchor.get("href")
            if not href:
                continue
            absolute = normalize_product_url(base_url, href, url_normalizer=url_normalizer)
            builder = anchor_context_builder or default_anchor_context
            contexts = list(builder(anchor, absolute))
            add(absolute, *contexts)
            if len(urls) >= limit:
                return

        if not allow_embedded_html_urls or len(urls) >= limit:
            return

        for match in re.findall(r'["\']([^"\']*/products/[^"\']+)["\']', html or "", re.I):
            add(match, match)
            if len(urls) >= limit:
                return

    def fetch_json(path: str, params: Dict[str, Any]) -> None:
        try:
            response = session.get(base_url + path, params=params, headers=headers, timeout=timeout)
        except Exception:
            return
        if not getattr(response, "ok", False):
            return
        try:
            data = response.json()
        except Exception:
            data = None
        finally:
            try:
                response.close()
            except Exception:
                pass
        if data is not None:
            add_from_json_payload(data)

    def fetch_html(path: str, params: Dict[str, Any]) -> None:
        try:
            response = session.get(base_url + path, params=params, headers=headers, timeout=timeout)
        except Exception:
            return
        if not getattr(response, "ok", False):
            return
        try:
            add_from_html(response.text or "")
        finally:
            try:
                response.close()
            except Exception:
                pass

    fetch_json("/search/suggest.json", {
        "q": request_query,
        "resources[type]": "product",
        "resources[limit]": suggest_limit,
        "resources[options][unavailable_products]": unavailable_products,
    })
    if len(urls) >= limit:
        return urls[:limit]

    if allow_search_json:
        fetch_json("/search.json", {
            "q": request_query,
            "type": "product",
            "limit": search_json_limit,
        })
        if len(urls) >= limit:
            return urls[:limit]

    for path in search_paths:
        fetch_html(path, {"q": request_query, "type": "product"})
        if len(urls) >= limit:
            break

    return urls[:limit]

from __future__ import annotations

import html as html_lib
import json
import re
import difflib
from xml.etree import ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 20
READER_TIMEOUT = 12
SCRAPER_VERSION = "notino-FR-generic-discovery-2026-08-21-v12-generic-seo-url-sitemap-discovery"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
READER_HEADERS = {
    "User-Agent": "ScentHunter/1.0",
    "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

PRODUCT_RE = re.compile(r"/p-\d+(?:/|$)", re.I)
# Notino uses both numeric-ID URLs and SEO-only product URLs.
PRODUCT_URL_RE = re.compile(r'https?://(?:www\.)?notino\.fr/[^\s)\]>\" ]+', re.I)
READER_ABSOLUTE_PRODUCT_RE = re.compile(
    r"(?:https?:)?(?:\/\/|//)(?:www\.?)*notino\.fr(?:\/|/)[^\s<>)\]\"']+",
    re.I,
)
READER_RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>)\]\"']*/)+[^\s<>)\]\"']+", re.I
)
PRICE_RE = re.compile(r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)", re.I)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)
CHALLENGE_MARKERS = (
    "just a moment", "cf-chl-", "challenge-platform", "checking your browser",
    "verify you are human", "enable javascript and cookies",
    "vérification de sécurité en cours",
)
IN_STOCK_MARKERS = ("en stock", "ajouter au panier", "add to cart")
OUT_STOCK_MARKERS = (
    "en rupture de stock", "rupture de stock",
    "actuellement indisponible", "produit indisponible",
)

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "set", "discovery set", "fragrance set",
    "perfume set", "parfum set", "coffret", "bundle", "pack", "travel set",
    "kit", "duo", "trio", "mystery box", "tester", "testeur", "sample",
    "shampoo", "shower gel", "body wash", "body lotion", "body cream",
    "body milk", "deodorant", "deo spray", "aftershave", "after shave",
    "body spray", "hair mist", "makeup", "cosmetics", "cosmetic",
    "skincare", "skin care", "cosmetici",
}

# Generic product-format expressions. They are metadata, not part of the
# product title, so they must not make discovery fail when the title omits them.
SIZE_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|dl|l|oz|fl\s*oz|g|kg)\b", re.I
)


def _product_norm(value: Any) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _has_non_perfume_marker(value: Any) -> bool:
    tokens = set(_product_norm(value).split())
    return any(
        set(_product_norm(marker).split()).issubset(tokens)
        for marker in NON_PERFUME_MARKERS
        if _product_norm(marker)
    )


def _has_non_perfume_marker_in_product(
    name: Any,
    url: Any = "",
    title: Any = "",
) -> bool:
    """Reject generic non-single-product formats without inspecting prose.

    Notino can expose a set/coffret with a short visible name such as the
    fragrance name alone. The product URL/title often carries the actual
    format (for example ``coffret-cadeau`` or ``duo``), so those structured
    product identifiers are checked together. We deliberately do not inspect
    the full product-page body because descriptions can mention gift sets
    without the product itself being a set.
    """
    for value in (name, title):
        if _has_non_perfume_marker(value):
            return True

    try:
        path = unquote(urlparse(str(url or "")).path)
    except Exception:
        path = str(url or "")

    return _has_non_perfume_marker(path)


def _clean(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ÿ])", r"\1 \2", text)


def _tokens(value: Any) -> List[str]:
    return [x for x in re.findall(r"[a-z0-9]+", _clean(value).lower()) if len(x) > 1]


def _query_tokens(value: Any) -> List[str]:
    """Return title/search tokens while ignoring generic size metadata."""
    text = _clean(value)
    text = SIZE_RE.sub(" ", text)
    return _tokens(text)


def _fuzzy_query_match(name: Any, query: Any) -> Tuple[bool, Dict[str, bool], int]:
    """Generic token matching with a conservative fuzzy fallback.

    Exact tokens are preferred. A fuzzy token is accepted only when the
    normalized similarity is high enough, which allows minor spelling
    minor spelling variants without creating product-specific rules.
    """
    name_tokens = set(_query_tokens(name))
    query_tokens = _query_tokens(query)
    if not query_tokens or not name_tokens:
        return False, {}, 0
    hits: Dict[str, bool] = {}
    fuzzy_hits = 0
    for token in query_tokens:
        if token in name_tokens:
            hits[token] = True
            continue
        best = max((difflib.SequenceMatcher(None, token, candidate).ratio() for candidate in name_tokens), default=0.0)
        hit = best >= 0.80 and abs(len(token) - max((len(x) for x in name_tokens), default=0)) <= 2
        hits[token] = hit
        fuzzy_hits += int(hit)
    return all(hits.values()), hits, fuzzy_hits


def _requested_sizes(value: Any) -> List[Tuple[str, str]]:
    sizes: List[Tuple[str, str]] = []
    for match in SIZE_RE.finditer(_clean(value)):
        number = match.group(1).replace(",", ".")
        unit = re.sub(r"\s+", "", match.group(2).lower())
        sizes.append((number, unit))
    return sizes


def _size_matches(text: Any, size: Tuple[str, str]) -> bool:
    number, unit = size
    pattern = re.compile(
        rf"\b{re.escape(number).replace(r'\.', r'[.,]')}\s*{re.escape(unit).replace('floz', r'fl\s*oz')}\b",
        re.I,
    )
    return bool(pattern.search(_clean(text)))


def _contains_requested_size(text: Any, query: Any) -> bool:
    requested = _requested_sizes(query)
    if not requested:
        return True
    return any(_size_matches(text, size) for size in requested)


def _matches(text: Any, query: Any) -> bool:
    text = _clean(text).lower()
    tokens = _query_tokens(query)
    return bool(tokens) and all(token in text for token in tokens)


def _format_price(value: Any) -> str:
    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", _clean(value))
    if not match:
        return ""
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return ""
    return f"{number:.2f}".replace(".", ",") + "€" if number > 0 else ""


def _extract_price(text: Any) -> str:
    matches = list(PRICE_RE.finditer(_clean(text)))
    if not matches:
        return ""
    m = matches[-1]
    return _format_price(m.group(1) or m.group(2))


def _extract_product_price(text: Any) -> str:
    """Extract the product selling price, never the unit price.

    Notino product pages commonly expose both values, for example:
    ``150 ml 40,00 €`` followed by ``26,67 € / 100 ml``.
    The price immediately associated with the product size is the actual
    selling price; a value followed by ``/ 100 ml`` is a unit price and is
    deliberately ignored.
    """
    content = _clean(text)
    if not content:
        return ""

    current_matches = list(re.finditer(
        r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        content,
        flags=re.I,
    ))
    for current in reversed(current_matches):
        after = content[current.end():current.end() + 30].lower()
        if not re.match(r"\s*/\s*100\s*(?:ml|g)", after):
            return _format_price(current.group(1))

    sized_prices = re.findall(
        r"\b\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\s+"
        r"(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        content,
        flags=re.I,
    )
    if sized_prices:
        return _format_price(sized_prices[-1])

    price_before_size = re.findall(
        r"(?:€\s*)?(\d{1,4}[.,]\d{2})\s*€?\s+"
        r"\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\b",
        content,
        flags=re.I,
    )
    if price_before_size:
        return _format_price(price_before_size[-1])

    # Prefer prices that are not immediately presented as a unit price.
    valid = []
    for match in PRICE_RE.finditer(content):
        end = content[match.end():match.end() + 30].lower()
        if re.match(r"\s*/\s*100\s*(?:ml|g)", end):
            continue
        valid.append(match.group(1) or match.group(2))
    if valid:
        return _format_price(valid[-1])
    return ""


def _is_excluded_notino_path(path: str) -> bool:
    low = (path or "").rstrip("/").lower()
    return any(low.startswith(prefix) for prefix in (
        "/search", "/avis/", "/erfahrungen/", "/magazine/", "/blog/",
        "/panier", "/cart", "/login", "/compte", "/account",
    ))


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return False
    path = parsed.path.rstrip("/")
    if _is_excluded_notino_path(path):
        return False
    segments = [x for x in path.split("/") if x]
    return len(segments) >= 2


def _normalise_reader_url(raw: Any) -> Optional[str]:
    value = html_lib.unescape(str(raw or "")).strip()
    value = value.replace("\\/", "/").replace("\\u002F", "/")
    value = unquote(value).strip(" <>\"'()[]{}.,;")
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return None
    path = parsed.path
    while path.lower().startswith("/www.notino.fr/") or path.lower().startswith("/notino.fr/"):
        path = "/" + path.split("/", 2)[2]
    normalised = f"https://{parsed.netloc.lower()}{path.rstrip('/')}"
    return normalised if _looks_like_product_url(normalised) else None

def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [f"{SEARCH_URL}?exps={q}", f"{BASE_URL}/search?query={q}"]


def _request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response


def _reader_request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(
        READER_BASE + url,
        headers=READER_HEADERS,
        timeout=READER_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _is_challenge(text: str) -> bool:
    low = _clean(text).lower()
    return any(x in low for x in CHALLENGE_MARKERS)


def _clean_name(text: str) -> str:
    value = RATING_RE.sub(" ", _clean(text))
    value = PRICE_RE.sub(" ", value)
    value = re.sub(
        r"^(?:promo|nouveau|discount|cadeaux? offerts|livraison offerte)\s+",
        "",
        value,
        flags=re.I,
    )
    words = value.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            value = " ".join(words[:half])
    return _clean(value)


def _card_text(link) -> str:
    node = link
    best = _clean(link.get_text(" ", strip=True))
    for _ in range(10):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if len(text) > len(best):
            best = text
        if 40 <= len(text) <= 1200 and _extract_price(text):
            return text
    return best


def _make_candidate(url: str, anchor: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = _clean(url).split("?")[0]
    if not _looks_like_product_url(url):
        return None
    anchor = _clean(anchor)
    card = _clean(card)
    name = _clean_name(anchor) or _clean_name(card)
    if not name or _has_non_perfume_marker_in_product(name, url, anchor):
        return None

    matched, hits, fuzzy_hits = _fuzzy_query_match(name, query)
    query_tokens = _query_tokens(query)
    if not query_tokens:
        return None
    score = sum(hits.values()) * 5 + fuzzy_hits * 2
    if matched:
        score += 5

    search_context = f"{anchor} {card}"
    requested_sizes = _requested_sizes(query)
    if requested_sizes:
        if any(_size_matches(search_context, size) for size in requested_sizes):
            score += 6
        else:
            # Size is validated later on the product page; do not discard a
            # valid candidate merely because the search-card title omits it.
            score -= 1

    if _extract_price(anchor) or _extract_price(card):
        score += 1

    return {
        "url": url,
        "anchor_text": anchor or name,
        "card_text": card or anchor,
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": matched,
        "requested_size": bool(requested_sizes),
        "size_match_in_search_context": (
            any(_size_matches(search_context, size) for size in requested_sizes)
            if requested_sizes else True
        ),
        "source": source,
    }


def extract_candidates_from_html(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for link in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, _clean(link.get("href"))).split("?")[0]
        if not _looks_like_product_url(url):
            continue
        candidate = _make_candidate(
            url,
            _clean(link.get_text(" ", strip=True)),
            _card_text(link),
            query,
            "direct-search",
        )
        if candidate and (
            candidate["url"] not in found
            or candidate["score"] > found[candidate["url"]]["score"]
        ):
            found[candidate["url"]] = candidate
    return sorted(
        found.values(),
        key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]),
    )


def _reader_name_from_context(context: str, query: str) -> str:
    """Recover a product name from structured Markdown headings only.

    Notino/Jina commonly emits the brand as ``##`` and the product as ``###``.
    The surrounding prose/card text is deliberately ignored.  This prevents
    neighbouring products from contaminating the candidate name.
    """
    raw = html_lib.unescape(context or "").replace("\\/", "/")
    lines = [
        re.sub(r"\s+", " ", x).strip()
        for x in str(raw).splitlines()
        if x.strip()
    ]

    headings: List[Tuple[int, str]] = []
    for line in lines:
        match = re.match(r"^(###|##)\s*(.+)$", line)
        if not match:
            continue
        headings.append(
            (
                3 if match.group(1) == "###" else 2,
                _clean_name(match.group(2)).strip(" <>[]()"),
            )
        )

    if not headings:
        return ""

    level, title = headings[-1]
    if not title:
        return ""

    if level == 3:
        # Only combine an immediately preceding ## brand.  If another ###
        # occurs between the brand and this title, do not cross that boundary.
        for prev_level, brand in reversed(headings[:-1]):
            if prev_level == 3:
                break
            if prev_level == 2 and brand:
                query_tokens = _query_tokens(query)
                brand_tokens = _query_tokens(brand)
                brand_relevant = any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(None, bt, qt).ratio() >= 0.80
                        and abs(len(bt) - len(qt)) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )
                combined = _clean_name(f"{brand} {title}")
                if brand_relevant and _fuzzy_query_match(combined, query)[0]:
                    return combined
                return title if _fuzzy_query_match(title, query)[0] else ""

    return title if _fuzzy_query_match(title, query)[0] else ""

def _name_from_product_url(url: str) -> str:
    try:
        path = unquote(urlparse(url).path).strip("/")
    except Exception:
        return ""
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return ""
    slug = parts[-2] if parts[-1].startswith("p-") else parts[-1]
    slug = re.sub(r"-\d{5,}$", "", slug)
    slug = re.sub(r"[-_]+", " ", slug)
    return _clean_name(slug)


def _brand_from_product_url(url: str) -> str:
    """Return first path component for both SEO and numeric-ID product URLs."""
    try:
        path = unquote(urlparse(url).path).strip("/")
    except Exception:
        return ""
    parts = [p for p in path.split("/") if p]
    return _clean_name(parts[0].replace("-", " ")) if len(parts) >= 2 else ""


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    raw = html_lib.unescape(text or "").replace("\\/", "/")
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    markdown = re.compile(r"\[([^\]]+)\]\(([^)]+)\)", re.I)

    for i, line in enumerate(lines):
        for match in markdown.finditer(line):
            anchor = _clean(match.group(1))
            url = _normalise_reader_url(match.group(2))
            if not url:
                continue

            # 1) The link text is the primary name source.
            name = _clean_name(anchor)

            # 2) If the link text is only the product heading, recover the
            # structured ## brand + ### product pair nearby.  Only Markdown
            # headings are inspected; arbitrary surrounding card text is not.
            query_tokens = _query_tokens(query)
            name_tokens = set(_query_tokens(name))
            # Only inspect structured headings when the anchor itself is
            # missing a query token. This keeps discovery fast while still
            # recovering a brand heading combined with its product heading.
            needs_heading = not query_tokens or not all(
                token in name_tokens for token in query_tokens
            )
            if needs_heading:
                heading_context = "\n".join(lines[max(0, i - 80):i + 1])
                heading_name = _reader_name_from_context(heading_context, query)
                if heading_name:
                    name = heading_name

            # 3) The product slug is the next source of truth.
            slug_name = _name_from_product_url(url)
            if slug_name and (
                not name
                or not _fuzzy_query_match(name, query)[0]
                or _has_non_perfume_marker(name)
            ):
                name = slug_name

            # 4) If the query itself contains the brand, combine the URL
            # brand path with the slug. This is generic and fixes cases where
            # Notino's search reader omits the ## brand from the anchor.
            brand = _brand_from_product_url(url)
            if brand:
                query_tokens = _query_tokens(query)
                brand_tokens = _query_tokens(brand)
                brand_relevant = any(
                    bt in query_tokens
                    or any(
                        difflib.SequenceMatcher(None, bt, qt).ratio() >= 0.80
                        and abs(len(bt) - len(qt)) <= 2
                        for qt in query_tokens
                    )
                    for bt in brand_tokens
                )
                branded_name = _clean_name(f"{brand} {slug_name or name}")
                if brand_relevant and _fuzzy_query_match(branded_name, query)[0]:
                    name = branded_name

            if not name or not _fuzzy_query_match(name, query)[0]:
                continue
            if _has_non_perfume_marker_in_product(name, url, anchor):
                continue

            candidate = _make_candidate(url, name, anchor or name, query, "reader-markdown")
            if candidate and (url not in found or candidate["score"] > found[url]["score"]):
                found[url] = candidate

    # Raw product URLs are retained as a second discovery channel.  Their
    # names come from the URL, never from a large neighbouring text block.
    for pattern in (PRODUCT_URL_RE, READER_ABSOLUTE_PRODUCT_RE, READER_RELATIVE_PRODUCT_RE):
        for match in pattern.finditer(raw):
            url = _normalise_reader_url(match.group(0))
            if not url:
                continue

            slug_name = _name_from_product_url(url)
            if not slug_name:
                continue

            name = slug_name
            brand = _brand_from_product_url(url)
            branded_name = _clean_name(f"{brand} {slug_name}") if brand else ""
            query_tokens = _query_tokens(query)
            brand_tokens = _query_tokens(brand)
            brand_relevant = bool(brand_tokens) and any(
                bt in query_tokens
                or any(
                    difflib.SequenceMatcher(None, bt, qt).ratio() >= 0.80
                    and abs(len(bt) - len(qt)) <= 2
                    for qt in query_tokens
                )
                for bt in brand_tokens
            )
            if branded_name and brand_relevant and _fuzzy_query_match(branded_name, query)[0]:
                name = branded_name

            if _has_non_perfume_marker_in_product(name, url):
                continue
            if not _fuzzy_query_match(name, query)[0]:
                continue

            candidate = _make_candidate(url, name, name, query, "reader-url")
            if candidate and (url not in found or candidate["score"] > found[url]["score"]):
                found[url] = candidate

    return sorted(
        found.values(),
        key=lambda x: (
            not bool(x.get("contains_all_query_tokens")),
            -int(x.get("score") or 0),
            x["url"],
        ),
    )



def _rank_candidates_for_product_lookup(candidates: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, Any]]:
    """Keep the strongest generic discovery candidates for product-page lookup."""
    if not candidates:
        return []
    ordered = sorted(
        candidates,
        key=lambda x: (
            not bool(x.get("contains_all_query_tokens")),
            -int(x.get("score") or 0),
            x.get("url", ""),
        ),
    )
    exact = [x for x in ordered if x.get("contains_all_query_tokens")]
    return (exact if exact else ordered)[:limit]


def _parse_sitemap_xml(text: str) -> Tuple[str, List[str]]:
    try:
        root = ET.fromstring(text or "")
    except ET.ParseError:
        return "", []
    root_type = root.tag.rsplit("}", 1)[-1].lower()
    locs = []
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1].lower() == "loc" and elem.text:
            locs.append(html_lib.unescape(elem.text.strip()))
    return root_type, locs


def _sitemap_product_urls(text: str) -> List[str]:
    """Extract internal URLs from a sitemap urlset without requiring /p-id/."""
    root_type, locs = _parse_sitemap_xml(text)
    urls, seen = [], set()
    if root_type == "urlset":
        for value in locs:
            url = _normalise_reader_url(value)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls
    raw = html_lib.unescape(str(text or "")).replace("\\/", "/")
    for match in re.finditer(r"<loc>\s*(.*?)\s*</loc>", raw, flags=re.I | re.S):
        url = _normalise_reader_url(match.group(1).strip())
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls

def _sitemap_child_urls(text: str) -> List[str]:
    """Extract child sitemap URLs from an XML sitemap index."""
    root_type, locs = _parse_sitemap_xml(text)
    if root_type == "sitemapindex":
        return list(dict.fromkeys(x for x in locs if x.lower().endswith(".xml")))
    raw = html_lib.unescape(str(text or "")).replace("\\/", "/")
    out=[]
    for match in re.finditer(r"<loc>\s*(.*?)\s*</loc>", raw, flags=re.I | re.S):
        value=match.group(1).strip()
        if value.lower().endswith(".xml") and value not in out:
            out.append(value)
    return out


def _candidate_from_sitemap_url(url: str, query: str) -> Optional[Dict[str, Any]]:
    slug_name = _name_from_product_url(url)
    if not slug_name:
        return None
    brand = _brand_from_product_url(url)
    name = slug_name
    branded_name = _clean_name(f"{brand} {slug_name}") if brand else ""
    query_tokens = _query_tokens(query)
    brand_tokens = _query_tokens(brand)
    brand_relevant = bool(brand_tokens) and any(
        bt in query_tokens
        or any(
            difflib.SequenceMatcher(None, bt, qt).ratio() >= 0.80
            and abs(len(bt) - len(qt)) <= 2
            for qt in query_tokens
        )
        for bt in brand_tokens
    )
    if branded_name and brand_relevant:
        name = branded_name
    if _has_non_perfume_marker_in_product(name, url):
        return None
    matched, hits, fuzzy_hits = _fuzzy_query_match(name, query)
    if not matched:
        return None
    score = sum(hits.values()) * 5 + fuzzy_hits * 2 + 5
    return {
        "url": url,
        "anchor_text": name,
        "card_text": name,
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": True,
        "requested_size": bool(_requested_sizes(query)),
        "size_match_in_search_context": _contains_requested_size(name, query),
        "source": "sitemap",
    }


def _sitemap_discovery(
    query: str, session: requests.Session, max_child_sitemaps: int = 200
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generic fallback using Notino's own XML product sitemap(s)."""
    pages: List[Dict[str, Any]] = []
    candidates: Dict[str, Dict[str, Any]] = {}

    def consume(text: str, source_url: str) -> List[str]:
        found_urls = _sitemap_product_urls(text)
        for url in found_urls:
            candidate = _candidate_from_sitemap_url(url, query)
            if candidate:
                old = candidates.get(url)
                if old is None or candidate["score"] > old["score"]:
                    candidates[url] = candidate
        return found_urls

    try:
        try:
            response = _request(session, SITEMAP_URL)
            root_text = response.text or ""
            pages.append({
                "url": SITEMAP_URL,
                "status": response.status_code,
                "html_length": len(root_text),
                "source": "sitemap",
            })
        except requests.RequestException as exc:
            reader = _reader_request(session, SITEMAP_URL)
            root_text = reader.text or ""
            pages.append({
                "url": SITEMAP_URL,
                "status": getattr(getattr(exc, "response", None), "status_code", None),
                "error": f"{type(exc).__name__}: {exc}",
                "reader_status": reader.status_code,
                "reader_html_length": len(root_text),
                "source": "sitemap-reader",
            })

        direct_products = consume(root_text, SITEMAP_URL)
        child_sitemaps = _sitemap_child_urls(root_text)
        for child_url in child_sitemaps[:max_child_sitemaps]:
            try:
                try:
                    child = _request(session, child_url)
                    child_text = child.text or ""
                    child_status = child.status_code
                    child_source = "sitemap"
                except requests.RequestException:
                    child = _reader_request(session, child_url)
                    child_text = child.text or ""
                    child_status = child.status_code
                    child_source = "sitemap-reader"
                before = len(candidates)
                consume(child_text, child_url)
                pages.append({
                    "url": child_url,
                    "status": child_status,
                    "html_length": len(child_text),
                    "candidate_count": len(candidates) - before,
                    "source": child_source,
                })
                # We only enter sitemap fallback when ordinary discovery is
                # weak. Two strong exact hits are enough to avoid unnecessary
                # catalogue-wide requests while preserving generic discovery.
            except requests.RequestException as exc:
                pages.append({
                    "url": child_url,
                    "status": getattr(getattr(exc, "response", None), "status_code", None),
                    "error": f"{type(exc).__name__}: {exc}",
                    "source": "sitemap",
                })
    except requests.RequestException as exc:
        pages.append({
            "url": SITEMAP_URL,
            "status": getattr(getattr(exc, "response", None), "status_code", None),
            "error": f"{type(exc).__name__}: {exc}",
            "source": "sitemap",
        })

    return sorted(candidates.values(), key=lambda x: (-x["score"], x["url"])), pages


def _reader_discovery(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generic Jina-reader discovery with query variants and brand-page expansion."""
    query = _clean(query)
    tokens = _query_tokens(query)
    variants: List[str] = []
    for value in [query, " ".join(reversed(tokens)), *tokens]:
        value = _clean(value)
        if value and value not in variants:
            variants.append(value)

    candidates: Dict[str, Dict[str, Any]] = {}
    pages: List[Dict[str, Any]] = []

    def collect(url: str, variant: str, source_url: str) -> None:
        try:
            response = _reader_request(session, url)
            found = _reader_candidates(response.text, query)
            for candidate in found:
                old = candidates.get(candidate["url"])
                if old is None or candidate["score"] > old["score"]:
                    candidates[candidate["url"]] = candidate
            pages.append({
                "url": source_url,
                "query": variant,
                "reader_url": READER_BASE + source_url,
                "status": response.status_code,
                "html_length": len(response.text or ""),
                "candidate_count": len(found),
                "reader": True,
            })
        except requests.RequestException as exc:
            pages.append({
                "url": source_url,
                "query": variant,
                "reader_url": READER_BASE + source_url,
                "status": getattr(getattr(exc, "response", None), "status_code", None),
                "error": f"{type(exc).__name__}: {exc}",
            })

    for variant in variants:
        for search_url in _search_urls(variant):
            collect(search_url, variant, search_url)

    # Generic second-stage discovery: when a strong candidate reveals a brand,
    # inspect that brand's catalogue through Jina.  No product names or
    # product-specific URLs are hard-coded.
    strong = sorted(
        candidates.values(),
        key=lambda x: (
            not bool(x.get("contains_all_query_tokens")),
            -int(x.get("score") or 0),
        ),
    )[:8]
    brand_urls: List[str] = []
    for candidate in strong:
        brand = _brand_from_product_url(candidate["url"])
        if not brand:
            continue
        brand_slug = re.sub(r"\s+", "-", brand.lower())
        brand_url = f"{BASE_URL}/{brand_slug}/"
        if brand_url not in brand_urls:
            brand_urls.append(brand_url)

    for brand_url in brand_urls:
        collect(brand_url, f"brand:{brand_url.rsplit('/', 2)[-2]}", brand_url)

    # Generic third-stage discovery: once a brand is known, retry the
    # original search with the brand explicitly included. Some Notino
    # search/reader variants expose only one result unless the brand is
    # present in the query. This remains fully generic and contains no
    # product-specific names or URLs.
    # Retry the original search with each distinct brand only once.  The
    # previous implementation iterated over every strong candidate, which could
    # issue the exact same branded searches repeatedly when several candidates
    # belonged to the same brand.  That made the generic fallback unnecessarily
    # expensive and could cause the overall scraper timeout before discovery
    # reached the remaining stores.
    branded_queries: List[str] = []
    seen_branded_queries = set()
    for candidate in strong:
        brand = _brand_from_product_url(candidate["url"])
        if not brand:
            continue
        for branded_query in (f"{brand} {query}", f"{query} {brand}"):
            branded_query = _clean(branded_query)
            key = branded_query.casefold()
            if branded_query and key not in seen_branded_queries:
                seen_branded_queries.add(key)
                branded_queries.append(branded_query)

    for branded_query in branded_queries:
        for search_url in _search_urls(branded_query):
            collect(search_url, branded_query, search_url)

    # Generic fourth-stage discovery: if the storefront search/brand catalogue
    # still exposes fewer than two exact products, consult Notino's own XML
    # product sitemap. This is catalogue-wide and contains no product names,
    # seeds, or hard-coded product URLs.
    exact_count = sum(1 for x in candidates.values() if x.get("contains_all_query_tokens"))
    sitemap_pages: List[Dict[str, Any]] = []
    if exact_count < 2:
        sitemap_candidates, sitemap_pages = _sitemap_discovery(query, session)
        for candidate in sitemap_candidates:
            old = candidates.get(candidate["url"])
            if old is None or candidate["score"] > old["score"]:
                candidates[candidate["url"]] = candidate
    pages.extend(sitemap_pages)

    ordered = sorted(
        candidates.values(),
        key=lambda x: (
            not bool(x.get("contains_all_query_tokens")),
            -int(x.get("score") or 0),
            x["url"],
        ),
    )
    return ordered, {
        "query": query,
        "discovery_queries": variants,
        "search_urls": _search_urls(query),
        "pages": pages,
        "raw_product_urls": len(ordered),
        "candidate_urls": len(ordered),
        "raw_query_token_hits": [x for x in ordered if x["contains_all_query_tokens"]],
        "fallback": "jina-reader+sitemap",
    }


def _search_http_candidates(
    query: str, session: Optional[requests.Session] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    own = session is None
    if own:
        session = requests.Session()
        session.headers.update(HEADERS)
    candidates: Dict[str, Dict[str, Any]] = {}
    pages = []
    try:
        for url in _search_urls(query):
            try:
                response = _request(session, url)
            except requests.RequestException as exc:
                pages.append({
                    "url": url,
                    "status": getattr(getattr(exc, "response", None), "status_code", None),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            found = extract_candidates_from_html(response.text, query)
            for candidate in found:
                old = candidates.get(candidate["url"])
                if old is None or candidate["score"] > old["score"]:
                    candidates[candidate["url"]] = candidate
            pages.append({
                "url": url,
                "final_url": response.url,
                "status": response.status_code,
                "html_length": len(response.text or ""),
                "candidate_count": len(found),
                "cloudflare": _is_challenge(response.text),
                "source": "direct",
            })
            if found:
                break

        ordered = sorted(
            candidates.values(),
            key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]),
        )
        if ordered:
            return ordered, {
                "query": query,
                "search_urls": _search_urls(query),
                "pages": pages,
                "raw_product_urls": len(ordered),
                "candidate_urls": len(ordered),
                "raw_query_token_hits": [x for x in ordered if x["contains_all_query_tokens"]],
                "fallback": None,
            }

        reader_candidates, report = _reader_discovery(query, session)
        report["direct_pages"] = pages
        return reader_candidates, report
    finally:
        if own:
            session.close()


def _json_ld_products(soup: BeautifulSoup) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                types = item.get("@type", [])
                types = types if isinstance(types, list) else [types]
                if "Product" in types:
                    yield item


def _offer_data(offers: Any) -> Tuple[str, str]:
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return "", ""
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        availability = _clean(offer.get("availability")).lower()
        if any(x in availability for x in ("outofstock", "soldout", "discontinued")):
            continue
        price = _format_price(offer.get("price")) or _format_price(offer.get("lowPrice"))
        if price:
            return price, availability
    return "", ""


def _requested_size_is_valid(text: str, query: str) -> bool:
    requested = _requested_sizes(query)
    if not requested:
        return True
    # A page that contains an explicit different size must not be returned.
    # If the page contains the requested size, accept it. If no size is
    # exposed at all, leave the decision to the existing generic validation.
    explicit_sizes = SIZE_RE.findall(_clean(text))
    if not explicit_sizes:
        return True
    return any(_size_matches(text, size) for size in requested)


def _reader_product(text: str, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    content = _clean(text)
    if not _fuzzy_query_match(content + " " + candidate["url"], query)[0]:
        return None
    if not _requested_size_is_valid(content + " " + candidate.get("card_text", ""), query):
        return None

    name = ""
    for line in [
        re.sub(r"^#+\s*", "", x).strip()
        for x in (text or "").splitlines()
        if x.strip()
    ][:100]:
        line = _clean(line)
        if (
            _matches(line, query)
            and len(line) <= 220
            and not PRICE_RE.search(line)
            and not line.lower().startswith(
                ("image", "description", "composition", "avis", "prix actuel")
            )
        ):
            name = _clean_name(line)
            if name:
                break

    if not name:
        name = _clean_name(candidate.get("anchor_text") or candidate.get("card_text", ""))
    if not name or _has_non_perfume_marker_in_product(name, candidate.get("url", "")):
        return None

    matched, _, _ = _fuzzy_query_match(name, query)
    if not matched:
        return None

    price = ""
    current = re.search(
        r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        content,
        re.I,
    )
    if current:
        price = _format_price(current.group(1))
    if not price:
        price = _extract_product_price(content)
    if not price:
        stock = re.search(
            r"en\s+stock[^€]{0,120}?(\d{1,4}[.,]\d{2})\s*€",
            content,
            re.I,
        )
        if stock:
            price = _format_price(stock.group(1))
    if not price:
        price = _extract_product_price(candidate.get("anchor_text", "")) or _extract_product_price(
            candidate.get("card_text", "")
        )
    if not price:
        return None

    low = content.lower()
    if any(x in low for x in OUT_STOCK_MARKERS) and not any(
        x in low for x in IN_STOCK_MARKERS
    ):
        return None
    return {"store": STORE, "name": name, "price": price, "url": candidate["url"]}


def _card_availability(candidate: Dict[str, Any]) -> str:
    """Read stock state only from the candidate's own search-card context.

    This is used only when a product page is unavailable because of an anti-bot
    challenge. It prevents an out-of-stock card from being promoted to a real
    store offer while preserving valid in-stock cards from the same search page.
    """
    anchor = _clean(candidate.get("anchor_text") or "")
    card = _clean(candidate.get("card_text") or "")
    context = _clean(f"{anchor} {card}")
    low = context.lower()

    # Include the short French stock labels too.  They are checked before
    # in-stock markers because ``disponible`` is contained in ``indisponible``.
    out_markers = tuple(dict.fromkeys(
        _clean(x).lower()
        for x in (*OUT_STOCK_MARKERS,
                  "indisponible", "épuisé", "epuise",
                  "out of stock", "sold out", "unavailable")
        if _clean(x)
    ))
    in_markers = tuple(dict.fromkeys(
        _clean(x).lower()
        for x in (*IN_STOCK_MARKERS, "disponible", "available", "in stock")
        if _clean(x)
    ))

    has_out = any(marker in low for marker in out_markers if marker)
    has_in = any(marker in low for marker in in_markers if marker)

    if has_out:
        return "out_of_stock"
    if has_in:
        return "in_stock"
    return "unknown"


def _card_result(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    anchor = _clean(candidate.get("anchor_text") or "")
    card = _clean(candidate.get("card_text") or "")
    name = _clean_name(anchor)
    if not name or _has_non_perfume_marker_in_product(
        name, candidate.get("url", ""), anchor
    ):
        return None
    matched, _, _ = _fuzzy_query_match(name, query)
    if not matched:
        return None

    context = f"{anchor} {card}"
    if not _requested_size_is_valid(context, query):
        return None

    # A search-card fallback is allowed only when the card is not explicitly
    # marked out of stock. Direct product pages are authoritative when they are
    # accessible; this branch exists for Notino's Cloudflare-protected pages.
    if _card_availability(candidate) == "out_of_stock":
        return None

    price = _extract_price(anchor) or _extract_price(card)
    if not price:
        return None
    return {"store": STORE, "name": name, "price": price, "url": candidate["url"]}


def _product_details(
    session: requests.Session, candidate: Dict[str, Any], query: str
) -> Optional[Dict[str, Any]]:
    url = candidate["url"]
    try:
        response = _request(session, url)
    except requests.RequestException:
        try:
            return (
                _reader_product(_reader_request(session, url).text, candidate, query)
                or _card_result(candidate, query)
            )
        except requests.RequestException:
            return _card_result(candidate, query)

    final_url = response.url.split("?")[0]
    if _has_non_perfume_marker_in_product(
        candidate.get("name", ""), final_url
    ):
        return None
    if _is_challenge(response.text) or not _looks_like_product_url(final_url):
        try:
            return (
                _reader_product(_reader_request(session, url).text, candidate, query)
                or _card_result(candidate, query)
            )
        except requests.RequestException:
            return _card_result(candidate, query)

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))
    if not _requested_size_is_valid(page_text, query):
        return None

    name = price = ""
    for product in _json_ld_products(soup):
        product_name = _clean(product.get("name"))
        brand = product.get("brand")
        brand = (
            _clean(brand.get("name"))
            if isinstance(brand, dict)
            else _clean(brand)
        )
        if _matches(f"{brand} {product_name}", query):
            price, _ = _offer_data(product.get("offers"))
            if product_name and price:
                name = product_name
                break

    if not name:
        h1 = soup.find("h1")
        if h1 and _matches(h1.get_text(" ", strip=True), query):
            name = _clean(h1.get_text(" ", strip=True))
    if not name:
        title = soup.find("title")
        if title:
            candidate_name = _clean(title.get_text(" ", strip=True)).split("|")[0]
            if _matches(candidate_name, query):
                name = candidate_name
    if not name:
        return _card_result(candidate, query)

    page_title = _clean(title.get_text(" ", strip=True)) if title else ""
    if _has_non_perfume_marker_in_product(name, final_url, page_title):
        return None

    if not price:
        m = re.search(r"prix\s+actuel\s+(\d{1,4}[.,]\d{2})\s*€", page_text, re.I)
        if m:
            price = _format_price(m.group(1))
    if not price:
        m = re.search(
            r"en\s+stock\s*[|:]?\s*(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if m:
            price = _format_price(m.group(1))
    if not price:
        price = _extract_product_price(page_text)
    if not price:
        price = _extract_product_price(candidate.get("anchor_text", "")) or _extract_product_price(
            candidate.get("card_text", "")
        )

    low = page_text.lower()
    if any(x in low for x in OUT_STOCK_MARKERS) and not any(
        x in low for x in IN_STOCK_MARKERS
    ):
        return None
    return {"store": STORE, "name": name, "price": price, "url": final_url} if price else None


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        candidates, _ = _search_http_candidates(query, session=session)
        candidates = _rank_candidates_for_product_lookup(candidates, limit=8)
        results, seen = [], set()
        for candidate in candidates:
            result = _product_details(session, candidate, query)
            if not result:
                continue
            key = (
                result.get("url", "") + "|" + _clean(result.get("name"))
            ).lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
            if len(results) >= 10:
                break
        return results
    finally:
        session.close()


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "query": query,
            "error": "empty_query",
        }

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        candidates, discovery = _search_http_candidates(query, session=session)
        candidates_for_product_pages = _rank_candidates_for_product_lookup(candidates, limit=8)
        discovery["product_page_candidate_limit"] = 8
        discovery["candidate_urls_before_product_page_limit"] = len(candidates)
        product_pages = []
        for candidate in candidates_for_product_pages:
            try:
                response = _request(session, candidate["url"])
                product_pages.append({
                    "url": candidate["url"],
                    "status": response.status_code,
                    "final_url": response.url,
                    "html_length": len(response.text or ""),
                    "cloudflare": _is_challenge(response.text),
                    "reader_fallback": False,
                    "requested_size": _requested_sizes(query),
                    "size_match": _requested_size_is_valid(response.text, query),
                })
            except requests.RequestException as exc:
                try:
                    reader = _reader_request(session, candidate["url"])
                    product_pages.append({
                        "url": candidate["url"],
                        "status": getattr(getattr(exc, "response", None), "status_code", None),
                        "error": f"{type(exc).__name__}: {exc}",
                        "reader_status": reader.status_code,
                        "reader_html_length": len(reader.text or ""),
                        "reader_fallback": True,
                        "requested_size": _requested_sizes(query),
                        "size_match": _requested_size_is_valid(reader.text, query),
                    })
                except requests.RequestException as reader_exc:
                    product_pages.append({
                        "url": candidate["url"],
                        "status": None,
                        "error": f"{type(exc).__name__}: {exc}",
                        "reader_error": f"{type(reader_exc).__name__}: {reader_exc}",
                        "reader_fallback": True,
                    })

        return {
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "query": query,
            "search_url": _search_urls(query)[0],
            "discovery": discovery,
            "candidate_count": len(candidates),
            "candidates": candidates[:25],
            "product_pages": product_pages,
        }
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            diagnose(args.query) if args.diagnose else search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )

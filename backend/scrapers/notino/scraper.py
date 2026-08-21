from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 20
READER_TIMEOUT = 12
SCRAPER_VERSION = "notino-FR-deep-diagnostic-2026-08-21-v8-generic-name-ranking"

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
PRODUCT_URL_RE = re.compile(r"https?://(?:www\.)?notino\.fr/[^\s)\]>\"]+/p-\d+(?:/|\b)", re.I)
READER_ABSOLUTE_PRODUCT_RE = re.compile(
    r"(?:https?:)?(?:\\/\\/|//)(?:www\\?\.)?notino\\?\.fr(?:\\/|/)[^\s<>)\]\\\"']*?/p-\d+(?:\\/|/|\b)",
    re.I,
)
READER_RELATIVE_PRODUCT_RE = re.compile(
    r"/(?:[a-z0-9][^\s<>)\]\\\"']*/)+p-\d+(?:/|\b)", re.I
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


def _price_is_unit_or_non_purchase(context: str) -> bool:
    low = _clean(context).lower()
    if re.search(r"(?:/|par|pro|per)\s*(?:100\s*ml|100\s*g|l|liter|litre)", low, re.I):
        return True
    if re.search(r"(?:€/|eur/|price\s+per|prix\s+(?:au|par))", low, re.I):
        return True
    if any(marker in low for marker in (
        "livraison", "frais de livraison", "retrait personnel",
        "shipping", "delivery", "pickup", "retrait",
    )):
        return True
    if any(marker in low for marker in (
        "ancien prix", "old price", "prix barré", "prix barre",
        "was price", "prix précédent", "prix precedent",
    )):
        return True
    return False


def _extract_purchase_price(text: Any) -> str:
    """
    Extract the customer purchase price from generic product text.

    Unit prices (/100 ml, par 100 ml, €/l, etc.), shipping/pickup fees and
    clearly crossed/previous prices are never selected as the product price.
    Active purchase context such as 'En stock', 'Prix actuel' and cart
    markers receives priority. No product/store-specific values are used.
    """
    content = _clean(text)
    matches = list(PRICE_RE.finditer(content))
    if not matches:
        return ""

    ranked = []
    for match in matches:
        value = match.group(1) or match.group(2)
        start = max(0, match.start() - 180)
        end = min(len(content), match.end() + 180)
        context = content[start:end]
        low = context.lower()

        # Unit-price syntax must be directly attached to this candidate.
        # Do not inspect a broad window here: a later /100 ml price must not
        # disqualify the real purchase price immediately before it.
        before = content[max(0, match.start() - 18):match.start()]
        after = content[match.end():min(len(content), match.end() + 22)]
        if re.search(r"(?:/|par|pro|per)\s*(?:100\s*ml|100\s*g|l|liter|litre)\s*$", before, re.I):
            continue
        if re.match(r"^\s*(?:/|par|pro|per)\s*(?:100\s*ml|100\s*g|l|liter|litre)\b", after, re.I):
            continue
        if re.search(r"(?:€/|eur/|price\s+per|prix\s+(?:au|par))\s*$", before, re.I):
            continue
        local_start = max(0, match.start() - 45)
        local_end = min(len(content), match.end() + 45)
        local_context = content[local_start:local_end].lower()
        # Shipping/pickup prices are excluded when the shipping marker is
        # attached to the candidate. A genuine purchase price may still have
        # a shipping label later in the same product block, so active purchase
        # markers are allowed to override that wider context.
        shipping_local = any(marker in local_context for marker in (
            "livraison", "frais de livraison", "retrait personnel",
            "shipping", "delivery", "pickup", "retrait",
        ))
        active_local = bool(re.search(
            r"en\s+stock|prix\s+actuel|ajouter\s+au\s+panier|add\s+to\s+cart",
            local_context,
            re.I,
        ))
        if shipping_local and not active_local:
            continue

        score = 0
        after_local = content[match.end():min(len(content), match.end() + 70)].lower()
        if "plus avantageux" in after_local or "plus avantageuse" in after_local:
            score -= 80
        current_match = re.search(r"prix\s+actuel(?:\s+de)?", low, re.I)
        if current_match:
            score += max(0, 120 - abs((match.start() - start) - current_match.start()))

        stock_matches = list(re.finditer(r"en\s+stock", low, re.I))
        if stock_matches:
            nearest = min(abs((match.start() - start) - m.start()) for m in stock_matches)
            score += max(0, 110 - nearest)

        cart_matches = list(re.finditer(r"ajouter\s+au\s+panier|add\s+to\s+cart", low, re.I))
        if cart_matches:
            nearest = min(abs((match.start() - start) - m.start()) for m in cart_matches)
            score += max(0, 75 - nearest)

        if "quantité" in low or "quantite" in low or "quantity" in low:
            score += 10
        if re.search(r"\b(?:au|dans le)\s+panier\b", low, re.I):
            score += 8

        ranked.append((score, match.start(), value))

    if not ranked:
        return ""

    # Highest contextual score wins; later occurrence breaks ties, which keeps
    # the active price ahead of an earlier crossed/list price when context is equal.
    ranked.sort(key=lambda item: (item[0], item[1]))
    return _format_price(ranked[-1][2])


def _name_from_product_url(url: str) -> str:
    """Derive a validation name from a generic Notino product URL slug."""
    try:
        path = urlparse(url).path.rstrip("/")
        match = re.search(r"/([^/]+)/p-\d+/?$", path, re.I)
        if not match:
            return ""
        slug = unquote(match.group(1))
        slug = re.sub(r"[-_]+", " ", slug)
        return _clean_name(slug)
    except Exception:
        return ""


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
    if not PRODUCT_RE.search(path):
        return None
    return f"https://{parsed.netloc.lower()}{path.rstrip('/')}"


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"} or not PRODUCT_RE.search(parsed.path):
        return False
    return not any(
        x in parsed.path.lower()
        for x in ("/search", "/panier", "/cart", "/login", "/account", "/avis/", "/magazine")
    )


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




def _discovery_queries(query: str) -> List[str]:
    """Build generic fallback queries used only to widen Notino discovery.

    The original user query is always preserved for final product validation.
    This allows recovery when Notino returns an incomplete result set for the
    exact query, without introducing product-specific seeds or exceptions.
    """
    tokens = _query_tokens(query)
    queries: List[str] = []
    seen = set()

    def add(value: str) -> None:
        value = _clean(value)
        key = _product_norm(value)
        if not key or key in seen:
            return
        seen.add(key)
        queries.append(value)

    add(query)
    if len(tokens) > 1:
        add(" ".join(reversed(tokens)))
        for token in tokens:
            if len(token) >= 3:
                add(token)
    return queries[:6]


def _rank_candidate_for_original_query(candidate: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Add generic ranking evidence for the original user query."""
    name = _clean_name(candidate.get("name") or candidate.get("anchor_text") or "")
    query_norm = _product_norm(query)
    name_norm = _product_norm(name)
    query_tokens = set(_query_tokens(query))
    name_tokens = set(_query_tokens(name))
    candidate = dict(candidate)
    candidate["original_query"] = query
    candidate["original_query_matches"] = bool(query_tokens) and query_tokens.issubset(name_tokens)
    candidate["original_query_exact_phrase"] = bool(query_norm and query_norm in name_norm)
    candidate["original_query_extra_tokens"] = max(0, len(name_tokens - query_tokens))
    if candidate["original_query_matches"]:
        score = int(candidate.get("score") or 0) + 100
        if candidate["original_query_exact_phrase"]:
            score += 50
        score += max(0, 20 - candidate["original_query_extra_tokens"])
        candidate["score"] = score
    return candidate
def _make_candidate(url: str, anchor: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = _clean(url).split("?")[0]
    if not _looks_like_product_url(url):
        return None
    anchor = _clean(anchor)
    card = _clean(card)

    # Prefer the product name encoded in the product URL when it itself
    # matches the query. Search-card context can contain nearby sponsored
    # products or another product title, which can otherwise cause a valid
    # URL to inherit the wrong name. This is deliberately generic.
    url_name = _name_from_product_url(url)
    context_name = _clean_name(anchor) or _clean_name(card)
    name = url_name if url_name and _matches(url_name, query) else context_name
    if not name or _has_non_perfume_marker(name):
        return None

    query_tokens = _query_tokens(query)
    name_tokens = set(_product_norm(name).split())
    if not query_tokens or not all(token in name_tokens for token in query_tokens):
        return None

    hits = {token: token in name_tokens for token in query_tokens}
    score = sum(hits.values()) * 5
    if all(hits.values()):
        score += 5

    # Prefer the most direct product-name match when several valid products
    # contain all query tokens. Exact query phrases rank above variant names
    # and longer extensions, without naming any store/product-specific
    # exception. A query that explicitly contains the variant terms still
    # wins because those terms are part of query_tokens.
    query_phrase = _product_norm(query)
    name_norm = _product_norm(name)
    if query_phrase and query_phrase in name_norm:
        score += 20
    extra_tokens = max(0, len(set(_query_tokens(name))) - len(set(query_tokens)))
    score += max(0, 10 - extra_tokens)

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
        "contains_all_query_tokens": all(hits.values()),
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
    raw = html_lib.unescape(context or "").replace("\\/", "/")
    raw = _clean(raw)
    headings = re.findall(r"(?<!\S)(?:###|##)\s*([^#\n]+)", raw)
    if headings:
        heading = re.sub(r"https?://\S+", " ", headings[-1])
        name = _clean_name(heading).strip(" <>[]()")
        if name and _matches(name, query):
            return name
        return ""

    pieces = re.split(r"\n|(?<=\])\s*(?=\[)", raw)
    for piece in reversed(pieces):
        piece = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", piece)
        piece = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", piece)
        piece = re.sub(r"https?://\S+", " ", piece)
        name = _clean_name(piece).strip(" <>[]()")
        name = re.sub(r"^#+\s*", "", name)
        if name and _matches(name, query) and len(name) <= 220:
            return name
    return ""


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
            local_context = _clean(" ".join(lines[max(0, i - 2):i + 1]))
            name = _clean_name(anchor)
            if not name or not _matches(name, query):
                name = _reader_name_from_context(local_context, query)
            if not name:
                name = _name_from_product_url(url)
            if not name:
                continue
            candidate = _make_candidate(url, name, local_context, query, "reader-markdown")
            if candidate and (
                url not in found or candidate["score"] > found[url]["score"]
            ):
                found[url] = candidate

    for pattern in (PRODUCT_URL_RE, READER_ABSOLUTE_PRODUCT_RE, READER_RELATIVE_PRODUCT_RE):
        for match in pattern.finditer(raw):
            url = _normalise_reader_url(match.group(0))
            if not url:
                continue
            prefix = raw[max(0, match.start() - 700):match.start()]
            name = _reader_name_from_context(prefix, query)
            if not name:
                name = _name_from_product_url(url)
            if not name:
                continue
            suffix = raw[match.end():min(len(raw), match.end() + 220)]
            candidate = _make_candidate(
                url, name, _clean(prefix[-260:] + " " + suffix), query, "reader-url"
            )
            if candidate and (
                url not in found or candidate["score"] > found[url]["score"]
            ):
                found[url] = candidate

    for match in re.finditer(r"(?:href|url)\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
        url = _normalise_reader_url(match.group(1))
        if not url:
            continue
        prefix = raw[max(0, match.start() - 700):match.start()]
        name = _reader_name_from_context(prefix, query)
        if not name:
            name = _name_from_product_url(url)
        if not name:
            continue
        candidate = _make_candidate(url, name, prefix[-400:], query, "reader-href")
        if candidate and (url not in found or candidate["score"] > found[url]["score"]):
            found[url] = candidate

    return sorted(
        found.values(),
        key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]),
    )


def _reader_discovery(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    pages = []
    discovery_queries = _discovery_queries(query)
    for discovery_query in discovery_queries:
        for url in _search_urls(discovery_query):
            try:
                response = _reader_request(session, url)
                candidates = _reader_candidates(response.text, discovery_query)
                for candidate in candidates:
                    candidate = _rank_candidate_for_original_query(candidate, query)
                    old = found.get(candidate["url"])
                    if old is None or candidate["score"] > old["score"]:
                        found[candidate["url"]] = candidate
                pages.append({
                    "url": url,
                    "query": discovery_query,
                    "reader_url": READER_BASE + url,
                    "status": response.status_code,
                    "html_length": len(response.text or ""),
                    "candidate_count": len(candidates),
                    "reader": True,
                })
            except requests.RequestException as exc:
                pages.append({
                    "url": url,
                    "query": discovery_query,
                    "reader_url": READER_BASE + url,
                    "status": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "reader": True,
                })
    ordered = sorted(
        found.values(),
        key=lambda x: (
            not x.get("original_query_matches", False),
            not x.get("original_query_exact_phrase", False),
            -x["score"],
            x["url"],
        ),
    )
    return ordered, {
        "query": query,
        "discovery_queries": discovery_queries,
        "search_urls": _search_urls(query),
        "pages": pages,
        "raw_product_urls": len(ordered),
        "candidate_urls": len(ordered),
        "raw_query_token_hits": [x for x in ordered if x.get("original_query_matches", False)],
        "fallback": "jina-reader",
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
    discovery_queries = _discovery_queries(query)
    try:
        for discovery_query in discovery_queries:
            for url in _search_urls(discovery_query):
                try:
                    response = _request(session, url)
                except requests.RequestException as exc:
                    pages.append({
                        "url": url,
                        "query": discovery_query,
                        "status": getattr(getattr(exc, "response", None), "status_code", None),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                found = extract_candidates_from_html(response.text, discovery_query)
                for candidate in found:
                    candidate = _rank_candidate_for_original_query(candidate, query)
                    old = candidates.get(candidate["url"])
                    if old is None or candidate["score"] > old["score"]:
                        candidates[candidate["url"]] = candidate
                pages.append({
                    "url": url,
                    "query": discovery_query,
                    "final_url": response.url,
                    "status": response.status_code,
                    "html_length": len(response.text or ""),
                    "candidate_count": len(found),
                    "cloudflare": _is_challenge(response.text),
                    "source": "direct",
                })

        ordered = sorted(
            candidates.values(),
            key=lambda x: (
                not x.get("original_query_matches", False),
                not x.get("original_query_exact_phrase", False),
                -x["score"],
                x["url"],
            ),
        )
        if ordered:
            return ordered, {
                "query": query,
                "discovery_queries": discovery_queries,
                "search_urls": _search_urls(query),
                "pages": pages,
                "raw_product_urls": len(ordered),
                "candidate_urls": len(ordered),
                "raw_query_token_hits": [x for x in ordered if x.get("original_query_matches", False)],
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
    if not _matches(content + " " + candidate["url"], query):
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
    if not name or _has_non_perfume_marker(name):
        return None

    query_tokens = _query_tokens(query)
    name_tokens = set(_product_norm(name).split())
    if not query_tokens or not all(token in name_tokens for token in query_tokens):
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
        price = _extract_purchase_price(content)
    if not price:
        price = _extract_purchase_price(candidate.get("anchor_text", "")) or _extract_purchase_price(
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


def _card_result(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    anchor = _clean(candidate.get("anchor_text") or "")
    card = _clean(candidate.get("card_text") or "")
    name = _clean_name(anchor)
    if not name or _has_non_perfume_marker(name):
        return None
    query_tokens = _query_tokens(query)
    name_tokens = set(_product_norm(name).split())
    if not query_tokens or not all(token in name_tokens for token in query_tokens):
        return None

    context = f"{anchor} {card}"
    if not _requested_size_is_valid(context, query):
        return None

    price = _extract_purchase_price(anchor) or _extract_purchase_price(card)
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

    if not price:
        price = _extract_purchase_price(page_text)
    if not price:
        price = _extract_purchase_price(candidate.get("anchor_text", "")) or _extract_purchase_price(
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


def _price_evidence(text: str) -> Dict[str, Any]:
    content = _clean(text or "")
    matches = []
    for m in PRICE_RE.finditer(content):
        start = max(0, m.start() - 100)
        end = min(len(content), m.end() + 100)
        matches.append({
            "value": _format_price(m.group(1) or m.group(2)),
            "raw": m.group(0),
            "context": content[start:end],
            "has_per_100": bool(re.search(r"(?:/|par)\s*100\s*(?:ml|ml\b)", content[start:end], re.I)),
        })
    current = re.findall(r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", content, re.I)
    stock = re.findall(r"en\s+stock[^€]{0,120}?(\d{1,4}[.,]\d{2})\s*€", content, re.I)
    return {
        "all_prices": matches,
        "current_price_matches": [_format_price(x) for x in current],
        "in_stock_price_matches": [_format_price(x) for x in stock],
        "price_count": len(matches),
    }


def _diagnose_candidate(candidate: Dict[str, Any], query: str) -> Dict[str, Any]:
    name = _clean_name(candidate.get("anchor_text") or candidate.get("card_text") or "")
    query_tokens = _query_tokens(query)
    name_tokens = set(_product_norm(name).split())
    return {
        "url": candidate.get("url"),
        "anchor_text": candidate.get("anchor_text"),
        "card_text": candidate.get("card_text"),
        "name_used_for_validation": name,
        "query_tokens": query_tokens,
        "name_tokens": sorted(name_tokens),
        "token_hits": {token: token in name_tokens for token in query_tokens},
        "matches_query": bool(query_tokens) and all(token in name_tokens for token in query_tokens),
        "non_perfume": _has_non_perfume_marker(name),
        "requested_sizes": _requested_sizes(query),
        "size_match_in_card": _contains_requested_size(
            f"{candidate.get('anchor_text','')} {candidate.get('card_text','')}", query
        ),
        "price_evidence": _price_evidence(
            f"{candidate.get('anchor_text','')} {candidate.get('card_text','')}"
        ),
        "score": candidate.get("score"),
        "source": candidate.get("source"),
    }


def _diagnose_product_page(
    session: requests.Session, candidate: Dict[str, Any], query: str
) -> Dict[str, Any]:
    url = candidate["url"]
    report: Dict[str, Any] = {
        "url": url,
        "requested_sizes": _requested_sizes(query),
        "direct": {},
        "reader": {},
        "validation": {},
        "json_ld": [],
        "price_evidence": {},
        "final_search_result": None,
    }

    texts = []
    try:
        response = _request(session, url)
        report["direct"] = {
            "status": response.status_code,
            "final_url": response.url,
            "html_length": len(response.text or ""),
            "cloudflare": _is_challenge(response.text),
            "looks_like_product_url": _looks_like_product_url(response.url),
        }
        texts.append(("direct", response.text or ""))
    except requests.RequestException as exc:
        report["direct"] = {
            "status": getattr(getattr(exc, "response", None), "status_code", None),
            "error": f"{type(exc).__name__}: {exc}",
        }

    try:
        reader = _reader_request(session, url)
        report["reader"] = {
            "status": reader.status_code,
            "html_length": len(reader.text or ""),
            "cloudflare": _is_challenge(reader.text),
        }
        texts.append(("reader", reader.text or ""))
    except requests.RequestException as exc:
        report["reader"] = {
            "status": getattr(getattr(exc, "response", None), "status_code", None),
            "error": f"{type(exc).__name__}: {exc}",
        }

    for source, text in texts:
        content = _clean(text)
        page_info = {
            "source": source,
            "matches_query": _matches(content + " " + url, query),
            "requested_size_valid": _requested_size_is_valid(content + " " + candidate.get("card_text", ""), query),
            "has_in_stock_marker": any(x in content.lower() for x in IN_STOCK_MARKERS),
            "has_out_of_stock_marker": any(x in content.lower() for x in OUT_STOCK_MARKERS),
            "price_evidence": _price_evidence(content),
        }
        report["validation"][source] = page_info

        if source == "direct":
            soup = BeautifulSoup(text, "html.parser")
            for product in _json_ld_products(soup):
                product_name = _clean(product.get("name"))
                brand = product.get("brand")
                brand = _clean(brand.get("name")) if isinstance(brand, dict) else _clean(brand)
                price, availability = _offer_data(product.get("offers"))
                report["json_ld"].append({
                    "name": product_name,
                    "brand": brand,
                    "matches_query": _matches(f"{brand} {product_name}", query),
                    "price": price,
                    "availability": availability,
                    "offers_raw_type": type(product.get("offers")).__name__,
                })

    try:
        report["final_search_result"] = _product_details(session, candidate, query)
    except Exception as exc:
        report["final_search_result_error"] = f"{type(exc).__name__}: {exc}"

    return report


def diagnose(query: str) -> Dict[str, Any]:
    """Deep diagnostic only. It does not change the normal search path."""
    query = _clean(query)
    if not query:
        return {
            "diagnostic": True,
            "diagnostic_level": "deep",
            "scraper_version": SCRAPER_VERSION,
            "query": query,
            "error": "empty_query",
        }

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        candidates, discovery = _search_http_candidates(query, session=session)

        candidate_audit = [_diagnose_candidate(c, query) for c in candidates[:50]]
        product_pages = [
            _diagnose_product_page(session, candidate, query)
            for candidate in candidates[:25]
        ]

        return {
            "diagnostic": True,
            "diagnostic_level": "deep",
            "scraper_version": SCRAPER_VERSION,
            "query": query,
            "search_urls": _search_urls(query),
            "discovery": discovery,
            "candidate_count": len(candidates),
            "candidates": candidate_audit,
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

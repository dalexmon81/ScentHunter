from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

TIMEOUT = 20
SCRAPER_VERSION = "notino-FR-generic-discovery-2026-08-19-v1"

PRODUCT_ID_RE = re.compile(r"/p-\d+(?:/|$)", re.I)
PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)",
    re.I,
)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)

CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "verify you are human",
    "performing security verification",
    "enable javascript and cookies",
    "vérification de sécurité en cours",
)


# ---------------------------------------------------------------------------
# GENERIC NORMALIZATION / MATCHING
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: Any) -> List[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _clean(value).lower())
        if len(token) > 1
    ]


def _matches(text: Any, query: Any) -> bool:
    haystack = _clean(text).lower()
    tokens = _tokens(query)
    return bool(tokens) and all(token in haystack for token in tokens)


def _format_price(value: Any) -> str:
    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", _clean(value))
    if not match:
        return ""

    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return ""

    if number <= 0:
        return ""

    return f"{number:.2f}".replace(".", ",") + "€"


def _extract_price(text: Any) -> str:
    matches = list(PRICE_RE.finditer(_clean(text)))
    if not matches:
        return ""

    match = matches[-1]
    return _format_price(match.group(1) or match.group(2))


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return False

    if not PRODUCT_ID_RE.search(parsed.path):
        return False

    low = parsed.path.lower()
    blocked = (
        "/search",
        "/panier",
        "/cart",
        "/login",
        "/account",
        "/contact",
        "/livraison",
        "/conditions",
        "/magazine",
    )
    return not any(part in low for part in blocked)


# ---------------------------------------------------------------------------
# HTTP DISCOVERY
# ---------------------------------------------------------------------------


def _search_urls(query: str) -> List[str]:
    encoded = quote_plus(query)
    return [
        f"{SEARCH_URL}?exps={encoded}",
        f"{BASE_URL}/search?query={encoded}",
    ]


def _request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _extract_card_text(link) -> str:
    node = link
    best = _clean(link.get_text(" ", strip=True))

    # Product cards can be several levels above the anchor. We deliberately
    # use structure/text only; no product-specific selectors are used.
    for _ in range(10):
        node = getattr(node, "parent", None)
        if node is None:
            break

        text = _clean(node.get_text(" ", strip=True))
        if len(text) > len(best):
            best = text

        # Once the ancestor is clearly a compact result card, stop growing it.
        if len(text) >= 40 and len(text) <= 1200 and _extract_price(text):
            if len(_tokens(text)) >= 2:
                return text

    return best


def _clean_candidate_name(text: str, url: str = "") -> str:
    value = _clean(text)

    # Remove rating blocks and currency values while preserving the actual
    # product wording. These patterns are generic to result cards.
    value = RATING_RE.sub(" ", value)
    value = PRICE_RE.sub(" ", value)
    value = re.sub(r"\b\d{1,4}[.,]\d{2}\s*€\b", " ", value, flags=re.I)
    value = _clean(value)

    # Some result anchors repeat the same product text twice. Collapse an
    # exact repeated half without relying on a product name.
    words = value.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            value = " ".join(words[:half])

    # Strip only generic promotional labels when they appear at the beginning.
    value = re.sub(
        r"^(?:promo|nouveau|discount|cadeaux? offerts)\s+",
        "",
        value,
        flags=re.I,
    )
    return _clean(value)


def extract_candidates_from_html(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: Dict[str, Dict[str, Any]] = {}
    query_tokens = _tokens(query)

    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href", ""))
        if not href:
            continue

        url = urljoin(BASE_URL, href).split("?")[0]
        if not _looks_like_product_url(url):
            continue

        anchor_text = _clean(link.get_text(" ", strip=True))
        card_text = _extract_card_text(link)
        # Prefer evidence attached to this exact product link. This prevents
        # a large shared container from making an unrelated sibling product
        # look like a query match.
        direct_text = _clean(f"{anchor_text} {url}")
        direct_has_all = _matches(direct_text, query)
        card_has_all = _matches(card_text, query)

        if not direct_has_all and not card_has_all:
            continue

        # If the anchor itself is unrelated and only a very large ancestor
        # contains the query, reject it unless the URL also carries the query
        # tokens. The normal Notino result cards expose the product name in
        # the anchor, so this keeps discovery precise without product seeds.
        if not direct_has_all:
            url_low = url.lower()
            if not all(token in url_low for token in query_tokens):
                continue

        combined = _clean(f"{anchor_text} {card_text}")

        token_hits = {
            token: token in combined.lower()
            for token in query_tokens
        }
        hit_count = sum(1 for hit in token_hits.values() if hit)

        if not query_tokens or hit_count == 0:
            continue

        score = hit_count * 5
        if hit_count == len(query_tokens):
            score += 5
        if _extract_price(card_text):
            score += 1

        candidate = {
            "url": url,
            "anchor_text": anchor_text,
            "card_text": card_text,
            "score": score,
            "token_hits": token_hits,
            "contains_all_query_tokens": hit_count == len(query_tokens),
        }

        old = candidates.get(url)
        if old is None or candidate["score"] > old["score"]:
            candidates[url] = candidate

    return sorted(
        candidates.values(),
        key=lambda item: (
            not item["contains_all_query_tokens"],
            -item["score"],
            item["url"],
        ),
    )


def _search_http_candidates(
    query: str,
    session: Optional[requests.Session] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Generic HTTP discovery layer used by search() and diagnostics."""
    query = _clean(query)
    own_session = session is None
    if own_session:
        session = requests.Session()
        session.headers.update(HEADERS)

    candidates: Dict[str, Dict[str, Any]] = {}
    pages: List[Dict[str, Any]] = []

    try:
        for search_url in _search_urls(query):
            try:
                response = _request(session, search_url)
            except requests.RequestException as exc:
                pages.append({
                    "url": search_url,
                    "status": None,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            page_candidates = extract_candidates_from_html(
                response.text,
                query,
            )

            for candidate in page_candidates:
                url = candidate["url"]
                old = candidates.get(url)
                if old is None or candidate["score"] > old["score"]:
                    candidates[url] = candidate

            pages.append({
                "url": search_url,
                "final_url": response.url,
                "status": response.status_code,
                "html_length": len(response.text or ""),
                "candidate_count": len(page_candidates),
                "cloudflare": _is_challenge(response.text),
            })

            # The first successful search page is the primary discovery path.
            if page_candidates:
                break

    finally:
        if own_session:
            session.close()

    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            not item["contains_all_query_tokens"],
            -item["score"],
            item["url"],
        ),
    )

    report = {
        "query": query,
        "search_urls": _search_urls(query),
        "pages": pages,
        "raw_product_urls": len(candidates),
        "candidate_urls": len(ordered),
        "raw_query_token_hits": [
            item for item in ordered
            if item["contains_all_query_tokens"]
        ],
    }

    return ordered, report


# ---------------------------------------------------------------------------
# PRODUCT PAGE / CARD FALLBACK
# ---------------------------------------------------------------------------


def _is_challenge(html: str) -> bool:
    low = _clean(html).lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def _json_ld_products(soup: BeautifulSoup) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        stack: List[Any] = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]
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
        if any(term in availability for term in (
            "outofstock", "soldout", "discontinued"
        )):
            continue

        price = (
            _format_price(offer.get("price"))
            or _format_price(offer.get("lowPrice"))
        )
        if price:
            return price, availability

    return "", ""


def _product_details(
    session: requests.Session,
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    url = candidate["url"]

    try:
        response = _request(session, url)
    except requests.RequestException:
        # Cloudflare/product-page blocking is not allowed to erase a product
        # already discovered correctly from the search result page.
        return _card_result(candidate, query)

    final_url = response.url.split("?")[0]
    if not _looks_like_product_url(final_url):
        return _card_result(candidate, query)

    if _is_challenge(response.text):
        return _card_result(candidate, query)

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))
    low = page_text.lower()

    if any(term in low for term in (
        "rupture de stock",
        "en rupture",
        "actuellement indisponible",
        "produit indisponible",
    )):
        return None

    name = ""
    price = ""

    for product in _json_ld_products(soup):
        candidate_name = _clean(product.get("name"))
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = _clean(brand.get("name"))
        else:
            brand = _clean(brand)

        if not _matches(f"{brand} {candidate_name}", query):
            continue

        candidate_price, _ = _offer_data(product.get("offers"))
        if candidate_name and candidate_price:
            name = candidate_name
            price = candidate_price
            break

    if not name:
        h1 = soup.find("h1")
        if h1:
            candidate_name = _clean(h1.get_text(" ", strip=True))
            if _matches(candidate_name, query):
                name = candidate_name

    if not name:
        title = soup.find("title")
        if title:
            candidate_name = _clean(title.get_text(" ", strip=True)).split("|")[0]
            if _matches(candidate_name, query):
                name = candidate_name

    if not name:
        return _card_result(candidate, query)

    if not price:
        current = re.search(
            r"prix\s+actuel\s+(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if current:
            price = _format_price(current.group(1))

    if not price:
        stock_price = re.search(
            r"en\s+stock\s*[|:]?\s*(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if stock_price:
            price = _format_price(stock_price.group(1))

    if not price:
        price = _extract_price(candidate.get("card_text", ""))

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": final_url,
    }


def _card_result(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    text = _clean(candidate.get("card_text") or candidate.get("anchor_text"))
    if not _matches(text, query):
        return None

    price = _extract_price(text)
    if not price:
        return None

    name = _clean_candidate_name(
        candidate.get("anchor_text") or text,
        candidate.get("url", ""),
    )

    # Anchor text can be empty or promotional. In that case the card text is
    # the next generic source available.
    if not name or not _matches(name, query):
        name = _clean_candidate_name(text, candidate.get("url", ""))

    if not name or not _matches(name, query):
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": candidate["url"],
    }


# ---------------------------------------------------------------------------
# PUBLIC SCRAPER API
# ---------------------------------------------------------------------------


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates, _ = _search_http_candidates(query, session=session)
        results: List[Dict[str, Any]] = []
        seen = set()

        for candidate in candidates:
            result = _product_details(session, candidate, query)
            if not result:
                continue

            url = result.get("url", "")
            key = (url + "|" + _clean(result.get("name"))).lower()
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
    """Generic diagnostic. It never invents products or uses product seeds."""
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
        candidates, discovery = _search_http_candidates(
            query,
            session=session,
        )

        product_pages = []
        for candidate in candidates[:25]:
            try:
                response = _request(session, candidate["url"])
                product_pages.append({
                    "url": candidate["url"],
                    "status": response.status_code,
                    "final_url": response.url,
                    "html_length": len(response.text or ""),
                    "cloudflare": _is_challenge(response.text),
                })
            except requests.RequestException as exc:
                product_pages.append({
                    "url": candidate["url"],
                    "status": None,
                    "error": f"{type(exc).__name__}: {exc}",
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

    payload = diagnose(args.query) if args.diagnose else search(args.query)
    print(json.dumps(payload, ensure_ascii=False, indent=2))

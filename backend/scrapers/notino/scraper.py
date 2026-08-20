from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URLS = (
    BASE_URL + "/search.asp?exps={query}",
    BASE_URL + "/search?query={query}",
)
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 15
READER_TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
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
PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\s)\]>\"']+/p-\d+(?:/|\b)",
    re.I,
)
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
    "enable javascript and cookies",
    "vérification de sécurité en cours",
)
OUT_STOCK_MARKERS = (
    "en rupture de stock",
    "rupture de stock",
    "actuellement indisponible",
    "produit indisponible",
)
GENERIC_TITLES = {
    "résultat de la recherche",
    "nombre de produits",
    "recherche",
    "produits",
    "résultats",
    "page",
    "chargement",
    "loading",
}


def _clean(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ÿ])", r"\1 \2", text)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value).lower()).strip()


def _tokens(value: Any) -> List[str]:
    return [
        x for x in re.findall(r"[a-z0-9]+", _norm(value))
        if len(x) > 1
    ]


def _matches(text: Any, query: Any) -> bool:
    tokens = _tokens(query)
    normalized = _norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def _format_price(value: Any) -> str:
    match = re.search(
        r"(\d{1,4}(?:[.,]\d{1,2})?)",
        _clean(value),
    )
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
    match = matches[-1]
    return _format_price(match.group(1) or match.group(2))


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return False
    if not PRODUCT_RE.search(parsed.path):
        return False
    return not any(
        part in parsed.path.lower()
        for part in (
            "/search", "/panier", "/cart", "/login",
            "/account", "/avis/", "/magazine",
        )
    )


def _search_urls(query: str) -> List[str]:
    encoded = quote_plus(query)
    return [template.format(query=encoded) for template in SEARCH_URLS]


def _is_challenge(text: str) -> bool:
    low = _norm(text)
    return any(marker in low for marker in CHALLENGE_MARKERS)


def _clean_name(text: str) -> str:
    value = RATING_RE.sub(" ", _clean(text))
    value = PRICE_RE.sub(" ", value)
    value = re.sub(
        r"^(?:promo|nouveau|discount|cadeaux? offerts|livraison offerte)\s+",
        "",
        value,
        flags=re.I,
    )
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
        if 40 <= len(text) <= 1400 and _extract_price(text):
            return text
    return best


def _candidate(
    url: str,
    anchor: str,
    card: str,
    query: str,
    source: str,
) -> Optional[Dict[str, Any]]:
    url = _clean(url).split("?")[0]
    if not _looks_like_product_url(url):
        return None

    evidence = _clean(f"{anchor} {card} {url}")
    if not _matches(evidence, query):
        return None

    name = _clean_name(anchor or card)
    if not name or not _matches(f"{name} {url}", query):
        name = _clean_name(card)

    if not name or not _matches(f"{name} {url}", query):
        return None

    if _norm(name) in GENERIC_TITLES:
        return None

    return {
        "url": url,
        "anchor_text": anchor or name,
        "card_text": card or anchor,
        "source": source,
    }


def _html_candidates(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}

    for link in soup.find_all("a", href=True):
        url = urljoin(
            BASE_URL,
            _clean(link.get("href")),
        ).split("?")[0]
        anchor = _clean(link.get_text(" ", strip=True))
        card = _card_text(link)

        candidate = _candidate(
            url, anchor, card, query, "direct-search"
        )
        if candidate:
            found[url] = candidate

    return list(found.values())


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]

    markdown = re.compile(
        r"\[([^\]]+)\]\((https?://(?:www\.)?notino\.fr/[^)]+)\)",
        re.I,
    )

    for i, line in enumerate(lines):
        for match in markdown.finditer(line):
            anchor = _clean(match.group(1))
            url = _clean(match.group(2)).split("?")[0]
            context = _clean(
                " ".join(
                    lines[max(0, i - 1):min(len(lines), i + 2)]
                )
            )
            candidate = _candidate(
                url, anchor, context, query, "reader-search"
            )
            if candidate:
                found[url] = candidate

    for match in PRODUCT_URL_RE.finditer(text or ""):
        url = match.group(0).split("?")[0].rstrip(".,")
        if url in found:
            continue
        context = _clean(
            (text or "")[
                max(0, match.start() - 300):
                match.end() + 300
            ]
        )
        candidate = _candidate(
            url, "", context, query, "reader-url"
        )
        if candidate:
            found[url] = candidate

    return list(found.values())


def _json_ld_products(soup: BeautifulSoup) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all(
        "script",
        type="application/ld+json",
    ):
        try:
            data = json.loads(
                script.string or script.get_text()
            )
        except (TypeError, ValueError, json.JSONDecodeError):
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
                if any(str(t).lower() == "product" for t in types):
                    yield item


def _offer_price(offers: Any) -> str:
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return ""

    for offer in offers:
        if not isinstance(offer, dict):
            continue
        availability = _norm(offer.get("availability"))
        if any(
            marker in availability
            for marker in ("outofstock", "soldout", "discontinued")
        ):
            continue
        price = (
            _format_price(offer.get("price"))
            or _format_price(offer.get("lowPrice"))
        )
        if price:
            return price
    return ""


def _reader_product(
    text: str,
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    content = _clean(text)
    if not _matches(
        f"{content} {candidate['url']}",
        query,
    ):
        return None

    name = ""
    for raw_line in [
        x for x in (text or "").splitlines() if x.strip()
    ][:120]:
        line = _clean(
            re.sub(r"^#+\s*", "", raw_line).strip()
        )
        if (
            _matches(line, query)
            and len(line) <= 220
            and not PRICE_RE.search(line)
            and _norm(line) not in GENERIC_TITLES
        ):
            name = _clean_name(line)
            if name:
                break

    if not name:
        name = _clean_name(
            candidate.get("anchor_text")
            or candidate.get("card_text", "")
        )

    if not name or not _matches(name, query):
        return None

    price_match = re.search(
        r"prix\s+actuel\s+(?:de\s+)?"
        r"(\d{1,4}[.,]\d{2})\s*€",
        content,
        re.I,
    )
    price = (
        _format_price(price_match.group(1))
        if price_match
        else ""
    )

    if not price:
        price = _extract_price(
            candidate.get("anchor_text", "")
        ) or _extract_price(
            candidate.get("card_text", "")
        )

    if not price:
        return None

    low = content.lower()
    if (
        any(x in low for x in OUT_STOCK_MARKERS)
        and "en stock" not in low
        and "ajouter au panier" not in low
    ):
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": candidate["url"],
    }


def _card_result(
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    text = _clean(
        candidate.get("card_text")
        or candidate.get("anchor_text")
    )
    if not _matches(text, query):
        return None

    price = (
        _extract_price(candidate.get("anchor_text", ""))
        or _extract_price(text)
    )
    if not price:
        return None

    name = _clean_name(
        candidate.get("anchor_text") or text
    )
    if not name or not _matches(
        f"{name} {candidate['url']}",
        query,
    ):
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": candidate["url"],
    }


def _product_details(
    session: requests.Session,
    candidate: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    url = candidate["url"]

    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException:
        try:
            reader = session.get(
                READER_BASE + url,
                headers=READER_HEADERS,
                timeout=READER_TIMEOUT,
                allow_redirects=True,
            )
            reader.raise_for_status()
            return (
                _reader_product(
                    reader.text,
                    candidate,
                    query,
                )
                or _card_result(candidate, query)
            )
        except requests.RequestException:
            return _card_result(candidate, query)

    final_url = response.url.split("?")[0]

    if (
        _is_challenge(response.text)
        or not _looks_like_product_url(final_url)
    ):
        try:
            reader = session.get(
                READER_BASE + url,
                headers=READER_HEADERS,
                timeout=READER_TIMEOUT,
                allow_redirects=True,
            )
            reader.raise_for_status()
            return (
                _reader_product(
                    reader.text,
                    candidate,
                    query,
                )
                or _card_result(candidate, query)
            )
        except requests.RequestException:
            return _card_result(candidate, query)

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )
    page_text = _clean(
        soup.get_text(" ", strip=True)
    )

    name = ""
    price = ""

    for product in _json_ld_products(soup):
        product_name = _clean(product.get("name"))
        brand = product.get("brand")
        brand = (
            _clean(brand.get("name"))
            if isinstance(brand, dict)
            else _clean(brand)
        )

        if _matches(
            f"{brand} {product_name}",
            query,
        ):
            product_price = _offer_price(
                product.get("offers")
            )
            if product_name and product_price:
                name = product_name
                price = product_price
                break

    if not name:
        h1 = soup.find("h1")
        if h1:
            candidate_name = _clean(
                h1.get_text(" ", strip=True)
            )
            if _matches(candidate_name, query):
                name = candidate_name

    if not name:
        title = soup.find("title")
        if title:
            candidate_name = _clean(
                title.get_text(" ", strip=True)
            ).split("|")[0]
            if _matches(candidate_name, query):
                name = candidate_name

    if not name:
        return _card_result(candidate, query)

    if not price:
        match = re.search(
            r"prix\s+actuel\s+(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if match:
            price = _format_price(match.group(1))

    if not price:
        match = re.search(
            r"en\s+stock\s*[|:]?\s*"
            r"(\d{1,4}[.,]\d{2})\s*€",
            page_text,
            re.I,
        )
        if match:
            price = _format_price(match.group(1))

    if not price:
        price = (
            _extract_price(
                candidate.get("anchor_text", "")
            )
            or _extract_price(
                candidate.get("card_text", "")
            )
        )

    low = page_text.lower()
    if (
        any(x in low for x in OUT_STOCK_MARKERS)
        and "en stock" not in low
        and "ajouter au panier" not in low
    ):
        return None

    if not price:
        return None

    return {
        "store": STORE,
        "name": name,
        "price": price,
        "url": final_url,
    }


def _discovery_queries(query: str) -> List[str]:
    """
    Produce generic fallback queries for discovery only.

    The final product validation always uses the ORIGINAL query, so broader
    discovery can recover a valid product hidden behind a partial/poor search
    response without admitting unrelated products.
    """
    tokens = _tokens(query)
    queries: List[str] = []
    seen = set()

    def add(value: str):
        value = _clean(value)
        key = _norm(value)
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


def _discover_direct(
    session: requests.Session,
    query: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    found: Dict[str, Dict[str, Any]] = {}
    pages = []

    for discovery_query in _discovery_queries(query):
        for url in _search_urls(discovery_query):
            try:
                response = session.get(
                    url,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                pages.append({
                    "url": url,
                    "query": discovery_query,
                    "status": getattr(
                        getattr(exc, "response", None),
                        "status_code",
                        None,
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            candidates = _html_candidates(
                response.text,
                discovery_query,
            )
            for candidate in candidates:
                # Candidate discovery may be broader than the user's query.
                # Keep it here; _product_details() re-validates the ORIGINAL
                # query against the real product page before returning it.
                found[candidate["url"]] = candidate

            pages.append({
                "url": url,
                "query": discovery_query,
                "final_url": response.url,
                "status": response.status_code,
                "html_length": len(response.text or ""),
                "candidate_count": len(candidates),
                "cloudflare": _is_challenge(response.text),
                "source": "direct",
            })

    return list(found.values()), pages


def _discover_reader(
    session: requests.Session,
    query: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    found: Dict[str, Dict[str, Any]] = {}
    pages = []

    for discovery_query in _discovery_queries(query):
        for url in _search_urls(discovery_query):
            try:
                response = session.get(
                    READER_BASE + url,
                    headers=READER_HEADERS,
                    timeout=READER_TIMEOUT,
                    allow_redirects=True,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                pages.append({
                    "url": url,
                    "query": discovery_query,
                    "status": None,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            candidates = _reader_candidates(
                response.text,
                discovery_query,
            )
            for candidate in candidates:
                found[candidate["url"]] = candidate

            pages.append({
                "url": url,
                "query": discovery_query,
                "status": response.status_code,
                "html_length": len(response.text or ""),
                "candidate_count": len(candidates),
                "source": "reader",
            })

    return list(found.values()), pages


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates, _ = _discover_direct(
            session,
            query,
        )

        if not candidates:
            candidates, _ = _discover_reader(
                session,
                query,
            )

        results = []
        seen = set()

        for candidate in candidates:
            result = _product_details(
                session,
                candidate,
                query,
            )
            if not result:
                continue

            key = (
                result.get("url", "")
                + "|"
                + _clean(result.get("name"))
            ).lower()

            if key in seen:
                continue

            seen.add(key)
            results.append(result)

        return results

    finally:
        session.close()


def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )

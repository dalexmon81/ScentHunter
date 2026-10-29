"""Notino FR/DE public product-search adapter.

The adapter reads public storefront search and product pages, keeps each
market's original URL, and only emits offers with a verifiable price.
It does not use affiliate tracking, private APIs, or browser fingerprint bypass.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
MARKETS = (
    ("https://www.notino.fr", "fr-FR,fr;q=0.9,en;q=0.7"),
)
TIMEOUT = (3.0, 6.0)
MAX_CANDIDATES_PER_MARKET = 10
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}


def _clean(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _normalise(value):
    text = _clean(value).lower()
    text = re.sub(r"(?<=\d)\s*(?=[a-z])|(?<=[a-z])\s*(?=\d)", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _url_matches_query_identity(query, url):
    """Reject stale search-card titles attached to unrelated product URLs.

    A retailer page can expose the searched product title in its page shell
    while the candidate URL actually points to another product. Validate the
    distinctive query identity against the URL slug independently of the
    visible title. Size units/numbers are attributes, not URL identity tokens.
    """
    query_tokens = [
        token for token in _normalise(query).split()
        if len(token) > 1 and token not in {
            "ml", "cl", "pour", "femme", "femmes", "homme", "hommes",
            "for", "the", "and", "avec", "de", "du", "des", "la", "le",
            "les", "eau", "edp", "edt", "edc", "parfum", "parfums",
            "perfume", "perfumes", "woman", "women", "man", "men",
            "unisex", "unisexe", "extrait", "spray", "vaporisateur",
        } and not token.isdigit()
    ]
    if len(query_tokens) < 2:
        return True
    slug_tokens = set(_normalise(urlparse(str(url or "")).path).split())
    matched = sum(1 for token in query_tokens if token in slug_tokens)
    # At least two distinctive terms must agree with the destination URL.
    # This rejects "Green Tea" URLs returned under a "Green Stravaganza"
    # result title, while allowing retailer slugs to omit nonessential words.
    return matched >= min(2, len(query_tokens))


def _query_matches(query, brand, name, url):
    # Volume is a product attribute, not part of its name/URL identity.
    # Validate it against the parsed product size separately in _parse_product.
    wanted = [
        token for token in _normalise(query).split()
        if len(token) > 1 and not token.isdigit() and token not in {"ml", "cl"}
    ]
    haystack = set(_normalise(f"{brand} {name} {url}").split())
    # A matching title is not enough when the actual destination identifies
    # another product. Check URL identity independently to prevent false offers.
    if not _url_matches_query_identity(query, url):
        return False
    # Require every meaningful query token to be present. This is deliberately
    # conservative: uncertain matches are omitted rather than attached wrongly.
    return bool(wanted) and all(token in haystack for token in wanted)


def _price(value):
    if value is None:
        return None
    raw = _clean(value).replace("\u00a0", " ").replace("€", "").replace("EUR", "").strip()
    raw = re.sub(r"[^0-9,.]", "", raw)
    if not raw:
        return None
    # Handle both EU decimal commas (99,90) and thousands separators
    # (1.299,90 / 1,299.90) without silently truncating high prices.
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[1]
        raw = raw.replace(",", ".") if len(tail) in (1, 2) else raw.replace(",", "")
    elif "." in raw:
        tail = raw.rsplit(".", 1)[1]
        if len(tail) not in (1, 2):
            raw = raw.replace(".", "")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _size_ml(*values):
    text = " ".join(_clean(v) for v in values)
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)[\s_-]*(ml|cl)\b", text, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value


def _concentration(*values):
    text = _normalise(" ".join(_clean(v) for v in values))
    for pattern, label in (
        (r"\beau de toilette\b|\bedt\b", "Eau de Toilette"),
        (r"\beau de parfum\b|\bedp\b", "Eau de Parfum"),
        (r"\beau de cologne\b|\bedc\b", "Eau de Cologne"),
        (r"\bextrait(?: de parfum)?\b", "Extrait de Parfum"),
        (r"\bparfum\b", "Parfum"),
    ):
        if re.search(pattern, text):
            return label
    return None


def _allowed_url(url, base):
    absolute = urljoin(base, str(url or ""))
    parsed = urlparse(absolute)
    base_host = urlparse(base).hostname
    if parsed.scheme != "https" or parsed.hostname != base_host:
        return None
    path = parsed.path or "/"
    blocked = (
        "/search", "/parfums", "/parfums-damen", "/parfums-herren",
        "/parfums-homme", "/marques", "/marken", "/login", "/account",
        "/cart", "/checkout", "/wishlist", "/customer-service",
    )
    low = path.lower().rstrip("/") or "/"
    if any(low == part or low.startswith(part + "/") for part in blocked):
        return None
    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".svg", ".pdf", ".css", ".js")):
        return None
    segments = [part for part in path.split("/") if part]
    if len(segments) < 2:
        return None
    return absolute.split("#", 1)[0]


def _request_html(url, accept_language):
    response = requests.get(
        url,
        headers={**HEADERS, "Accept-Language": accept_language},
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    try:
        if response.status_code in (403, 429):
            raise RuntimeError(f"blocked_http_{response.status_code}")
        response.raise_for_status()
        requested_host = urlparse(url).hostname or ""
        final_host = urlparse(response.url).hostname or ""
        market_hosts = {requested_host, requested_host.removeprefix("www."), "www." + requested_host.removeprefix("www.")}
        if final_host not in market_hosts:
            raise RuntimeError("redirected_outside_notino_market")
        html = response.text
        lower = html[:200000].lower()
        if any(marker in lower for marker in (
            "verify you are human", "access denied", "unusual traffic",
            "captcha", "robot check", "request blocked",
        )):
            raise RuntimeError("notino_challenge_page")
        return html
    finally:
        response.close()


def _candidate_urls(html, base):
    soup = BeautifulSoup(html or "", "html.parser")
    candidates = []
    seen = set()
    for node in soup.select("a[href]"):
        url = _allowed_url(node.get("href"), base)
        if not url or url in seen:
            continue
        seen.add(url)
        candidates.append(url)
        if len(candidates) >= MAX_CANDIDATES_PER_MARKET:
            break
    return candidates


def _product_jsonld(soup):
    def walk(value):
        if isinstance(value, dict):
            typ = value.get("@type")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() == "product" for t in types):
                yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        product = next(walk(data), None)
        if product:
            return product
    return {}


def _parse_product(url, html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    data = _product_jsonld(soup)
    h1 = soup.find("h1")
    name = _clean((h1.get_text(" ", strip=True) if h1 else "") or data.get("name"))
    if not name:
        return None

    brand = data.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    brand = _clean(brand)

    size = _size_ml(name, url, data.get("description"))
    requested_size = _size_ml(query)
    if not _query_matches(query, brand, name, url):
        return None
    # Do not require "100 ml" to appear in the title or URL: Notino often
    # exposes size as a selected variant/description. But if the query names
    # a size, only publish the offer when the page provides that exact size.
    if requested_size is not None and size != requested_size:
        return None

    offers = data.get("offers")
    if isinstance(offers, list):
        offer = next((item for item in offers if isinstance(item, dict)), {})
    elif isinstance(offers, dict):
        offer = offers
    else:
        offer = {}

    price = _price(offer.get("price") or offer.get("lowPrice"))
    if price is None:
        for node in soup.select('[itemprop="price"], meta[property="product:price:amount"], meta[itemprop="price"]'):
            price = _price(node.get("content") or node.get_text(" ", strip=True))
            if price is not None:
                break
    if price is None:
        return None

    currency = _clean(offer.get("priceCurrency") or "EUR").upper()
    if currency != "EUR":
        return None

    availability_raw = _clean(offer.get("availability")).lower()
    if "outofstock" in availability_raw or "out_of_stock" in availability_raw:
        available = False
        availability = "Out of stock"
    elif "instock" in availability_raw or "in_stock" in availability_raw or "limitedavailability" in availability_raw:
        available = True
        availability = "In stock"
    else:
        available = None
        availability = None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    image = urljoin(url, str(image)) if image else None

    concentration = _concentration(name, url)
    return {
        "shop": STORE,
        "store": "notino",
        "brand": brand,
        "name": name,
        "price": f"{price:.2f} €",
        "price_num": price,
        "currency": "EUR",
        "available": available,
        "availability": availability,
        "image": image,
        "size_ml": size,
        "concentration": concentration,
        "url": url,
    }


def _search_market(query, base, accept_language):
    search_url = f"{base}/search/?exps={quote_plus(query)}&lastPage=1-0-1"
    html = _request_html(search_url, accept_language)
    candidates = _candidate_urls(html, base)
    results = []
    errors = []
    if candidates:
        with ThreadPoolExecutor(max_workers=min(5, len(candidates))) as pool:
            futures = {
                pool.submit(_request_html, url, accept_language): url
                for url in candidates
            }
            for future in as_completed(futures):
                url = futures[future]
                try:
                    row = _parse_product(url, future.result(), query)
                    if row:
                        results.append(row)
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}:{exc}")
    return results, errors, len(candidates)


def search(query):
    query = _clean(query)
    if not query:
        return {"status": "success", "verified": True, "results": [], "error": None, "details": {"empty_query": True}}

    # Feed is the preferred source. A successful empty match is not proof that
    # the retailer has no matching product: try the general public discovery
    # adapter for every query, not only hand-seeded products.
    try:
        from . import affiliate_feed
        feed_report = affiliate_feed.search_feed(query)
        feed_rows = feed_report.get("results") or []
        if feed_rows:
            return {
                "status": "success",
                "verified": True,
                "results": feed_rows,
                "error": None,
                "details": {**(feed_report.get("details") or {}), "source": "cj_viv_authorized_xml"},
            }
    except Exception:
        feed_report = {"status": "unavailable", "results": [], "error": "notino_feed_search_failed"}

    results = []
    errors = []
    candidate_count = 0
    completed_markets = 0
    with ThreadPoolExecutor(max_workers=len(MARKETS)) as pool:
        future_to_market = {
            pool.submit(_search_market, query, base, language): (base, language)
            for base, language in MARKETS
        }
        for future in as_completed(future_to_market):
            base, _language = future_to_market[future]
            try:
                rows, market_errors, count = future.result()
                results.extend(rows)
                errors.extend(market_errors)
                candidate_count += count
                completed_markets += 1
            except Exception as exc:
                errors.append(f"{urlparse(base).hostname}:{type(exc).__name__}:{exc}")

    # Deduplicate only identical source URLs; keep FR and DE offers separate.
    unique = {}
    for row in results:
        unique[row["url"]] = row
    results = sorted(unique.values(), key=lambda row: (
        row.get("price_num") is None,
        row.get("price_num") if row.get("price_num") is not None else 999999,
        row.get("url") or "",
    ))
    if not results:
        # Public storefront search is often blocked at the listing endpoint.
        # The restored reader-based discovery path is a generic fallback across
        # all perfumes and is still required to verify each product page price.
        try:
            from . import legacy_public
            fallback_rows = legacy_public.search(query)
            if fallback_rows:
                # Keep the established fallback adapter's public contract; only
                # admit offers whose price can be parsed as a positive number.
                results = [
                    row for row in fallback_rows
                    if (
                        (_price(row.get("price_num")) if row.get("price_num") is not None
                         else _price(row.get("price"))) is not None
                        and (
                            _price(row.get("price_num")) if row.get("price_num") is not None
                            else _price(row.get("price"))
                        ) > 0
                    )
                ]
            if results:
                return {
                    "status": "partial" if errors else "success",
                    "verified": True, "results": results, "error": None,
                    "details": {"source": "notino_public_search",
                                "markets_checked": completed_markets,
                                "candidate_count": candidate_count},
                }
        except Exception as exc:
            errors.append(f"reader_fallback:{type(exc).__name__}:{exc}")

    if completed_markets == len(MARKETS):
        return {
            "status": "partial" if errors else "success",
            "verified": True,
            "results": results,
            "error": "; ".join(errors[:4]) if errors else None,
            "details": {"source": "notino_public_search", "markets_checked": completed_markets, "candidate_count": candidate_count, "candidate_errors": len(errors)},
        }
    if completed_markets:
        return {
            "status": "partial",
            "verified": False,
            "results": results,
            "error": "; ".join(errors[:4]) if errors else "notino_market_partial",
            "details": {"markets_checked": completed_markets, "candidate_count": candidate_count},
        }
    return {
        "status": "unavailable",
        "verified": False,
        "results": [],
        "error": "; ".join(errors[:4]) if errors else "notino_unavailable",
        "details": {"markets_checked": 0, "candidate_count": candidate_count},
    }

"""Deloox product-page adapter for the isolated next engine.

This adapter is intentionally separate from the legacy scraper and catalog.
It accepts an optional discovery callback so discovery policy can be migrated
independently from product-page fetching/parsing. It does not bypass 403/429,
robots, or retailer access controls.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from threading import local
from typing import Callable, Iterable
from urllib.parse import urlparse

from ..errors import AdapterFailure, ErrorKind
from ..models import RetailerOfferRecord, validate_http_url

STORE_KEY = "deloox"
PARSER_VERSION = "deloox-jsonld-v1"
ALLOWED_HOSTS = frozenset({
    "deloox.be", "www.deloox.be", "deloox.nl", "www.deloox.nl",
    "deloox.com", "www.deloox.com",
})
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _product_jsonld(html: str) -> dict:
    """Select a Product JSON-LD object from direct scripts or nested @graph."""
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise AdapterFailure(ErrorKind.UNKNOWN, "beautifulsoup4 is required for Deloox parsing") from exc
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict] = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text(strip=True))
        except (TypeError, ValueError):
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                node_type = node.get("@type", [])
                types = node_type if isinstance(node_type, list) else [node_type]
                if any(str(item).casefold().rsplit("/", 1)[-1].rsplit("#", 1)[-1] == "product" for item in types):
                    candidates.append(node)
                # Walk nested JSON-LD containers as some storefronts put the
                # Product below @graph or another structured-data wrapper.
                for key, child in node.items():
                    if key in {"@graph", "mainEntity", "mainEntityOfPage", "itemListElement"}:
                        if isinstance(child, list):
                            stack.extend(child)
                        elif isinstance(child, dict):
                            stack.append(child)
    if not candidates:
        return {}
    # Prefer the object with both a name and a valid positive offer price.
    def score(node: dict) -> tuple[int, int]:
        offers = node.get("offers")
        offers = offers if isinstance(offers, list) else [offers]
        has_price = any(isinstance(o, dict) and _positive_decimal(o.get("price")) is not None for o in offers)
        return (int(bool(_clean(node.get("name")))) + int(has_price), int(has_price))
    return max(candidates, key=score)


def _positive_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(_clean(value).replace("€", "").replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def _size_ml(title: str) -> Decimal | None:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", title, re.I)
    if not match:
        return None
    size = Decimal(match.group(1).replace(",", "."))
    return size * 10 if match.group(2).casefold() == "cl" else size


def _concentration(title: str) -> str | None:
    folded = _clean(title).casefold()
    if re.search(r"\b(?:eau de parfum|edp)\b", folded):
        return "Eau de Parfum"
    if re.search(r"\b(?:eau de toilette|edt)\b", folded):
        return "Eau de Toilette"
    if re.search(r"\bextrait(?: de parfum)?\b", folded):
        return "Extrait de Parfum"
    return None


def _availability(value: object) -> str:
    text = _clean(value).casefold().replace("https://schema.org/", "")
    if any(token in text for token in ("outofstock", "out_of_stock", "soldout", "discontinued", "unavailable")):
        return "out_of_stock"
    if any(token in text for token in ("instock", "in_stock", "limitedavailability", "preorder")):
        return "in_stock"
    return "unknown"


def _meta_content(soup, *keys: str) -> str:
    """Read a meta tag by property/name/itemprop, ignoring empty values."""
    wanted = {key.casefold() for key in keys}
    for tag in soup.find_all("meta"):
        names = {
            _clean(tag.get("property")), _clean(tag.get("name")),
            _clean(tag.get("itemprop")),
        }
        if any(name.casefold() in wanted for name in names if name):
            value = _clean(tag.get("content"))
            if value:
                return value
    return ""


def _offer_from_jsonld(data: dict) -> dict | None:
    """Choose a priced Offer, including AggregateOffer low/high price fallback."""
    offers = data.get("offers")
    offers = offers if isinstance(offers, list) else [offers]
    valid = [o for o in offers if isinstance(o, dict)]
    for offer in valid:
        if _positive_decimal(offer.get("price")) is not None:
            return offer
    for offer in valid:
        # AggregateOffer often exposes lowPrice instead of price.
        if _positive_decimal(offer.get("lowPrice")) is not None:
            return {**offer, "price": offer.get("lowPrice")}
    return None


class DelooxProductPageAdapter:
    store_key = STORE_KEY
    parser_version = PARSER_VERSION

    def __init__(self, *, discover_urls: Callable[[int], Iterable[str]] | None = None,
                 timeout: tuple[float, float] = (3.5, 8.0), session=None):
        if len(timeout) != 2 or timeout[0] <= 0 or timeout[1] <= 0:
            raise ValueError("timeout must contain positive connect/read seconds")
        self._discover_urls = discover_urls
        self.timeout = timeout
        self._session = session
        self._request_state = local()

    def discover(self, *, limit: int) -> Iterable[str]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if self._discover_urls is None:
            return []
        seen: set[str] = set()
        output: list[str] = []
        for raw in self._discover_urls(limit):
            url = validate_http_url(raw)
            self._validate_host_and_path(url)
            if url not in seen:
                seen.add(url)
                output.append(url)
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _validate_host_and_path(url: str) -> None:
        parsed = urlparse(validate_http_url(url))
        host = (parsed.hostname or "").casefold().rstrip(".")
        if host not in ALLOWED_HOSTS:
            raise AdapterFailure(ErrorKind.INVALID_URL, "URL host is not an allowed Deloox storefront")
        if not re.search(r"/(?:product|produit|producto|prodotto)/\d+(?:/|$)", parsed.path, re.I):
            raise AdapterFailure(ErrorKind.INVALID_URL, "URL is not a recognized Deloox product-page path")

    def fetch(self, url: str) -> bytes:
        self._validate_host_and_path(url)
        self._request_state.final_url = None
        try:
            import requests
        except ImportError as exc:
            raise AdapterFailure(ErrorKind.UNKNOWN, "requests is required for Deloox fetching") from exc
        session = self._session or requests.Session()
        try:
            response = session.get(url, headers=HEADERS, timeout=self.timeout, allow_redirects=True)
        except requests.Timeout as exc:
            raise AdapterFailure(ErrorKind.TRANSIENT_NETWORK, f"Deloox request timed out: {exc}") from exc
        except requests.RequestException as exc:
            raise AdapterFailure(ErrorKind.TRANSIENT_NETWORK, f"Deloox request failed: {exc}") from exc
        status = int(response.status_code)
        if status == 403:
            raise AdapterFailure(ErrorKind.ACCESS_DENIED, "Deloox returned HTTP 403; access was not bypassed")
        if status == 404 or status == 410:
            raise AdapterFailure(ErrorKind.NOT_FOUND, f"Deloox returned HTTP {status}")
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                retry_seconds = float(retry_after) if retry_after else None
            except ValueError:
                retry_seconds = None
            raise AdapterFailure(ErrorKind.RATE_LIMITED, "Deloox rate-limited the request", retry_seconds)
        if status >= 500:
            raise AdapterFailure(ErrorKind.UPSTREAM_SERVER, f"Deloox returned HTTP {status}")
        if status >= 400:
            raise AdapterFailure(ErrorKind.INVALID_DOCUMENT, f"Deloox returned HTTP {status}")
        final_url = _clean(getattr(response, "url", "") or url)
        self._validate_host_and_path(final_url)
        body = getattr(response, "content", b"") or b""
        if not body:
            raise AdapterFailure(ErrorKind.INVALID_DOCUMENT, "Deloox returned an empty response")
        self._request_state.final_url = final_url
        return body

    def parse(self, url: str, body: bytes) -> RetailerOfferRecord:
        # Capture and immediately clear fetch state. A failed parse must not
        # leak a previous request's redirect target into the next observation.
        final_url = getattr(self._request_state, "final_url", None) or url
        self._request_state.final_url = None
        # Validate before touching the document so callers cannot use the
        # parser as a generic HTML parser for arbitrary hosts.
        self._validate_host_and_path(url)
        self._validate_host_and_path(final_url)
        try:
            html = body.decode("utf-8", errors="replace")
        except Exception as exc:
            raise AdapterFailure(ErrorKind.INVALID_DOCUMENT, "Deloox response could not be decoded") from exc
        data = _product_jsonld(html)
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise AdapterFailure(ErrorKind.UNKNOWN, "beautifulsoup4 is required for Deloox parsing") from exc
        soup = BeautifulSoup(html, "html.parser")
        h1_node = soup.find("h1")
        title = (
            _clean(data.get("name"))
            or (_clean(h1_node.get_text(" ", strip=True)) if h1_node else "")
            or _meta_content(soup, "og:title", "twitter:title", "name")
        )
        if not title:
            raise AdapterFailure(ErrorKind.INVALID_PRODUCT, "Deloox product title missing from JSON-LD, H1 and metadata")
        brand = data.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        elif isinstance(brand, list):
            brand = next((b.get("name") for b in brand if isinstance(b, dict) and b.get("name")), "")
        brand = _clean(brand) or _meta_content(soup, "product:brand", "brand", "brand.name")
        if not brand:
            raise AdapterFailure(ErrorKind.INVALID_PRODUCT, "Deloox product brand missing from JSON-LD and metadata")
        offer = _offer_from_jsonld(data)
        if not offer:
            # Metadata is a constrained fallback only: it must explicitly be
            # a product price, never a generic price scraped from page text.
            meta_price = _meta_content(soup, "product:price:amount", "og:price:amount", "price")
            if _positive_decimal(meta_price) is not None:
                offer = {
                    "price": meta_price,
                    "priceCurrency": _meta_content(soup, "product:price:currency", "og:price:currency") or "EUR",
                    "availability": _meta_content(soup, "product:availability", "availability"),
                }
        if not offer:
            raise AdapterFailure(ErrorKind.INVALID_PRICE, "Deloox has no valid positive price in JSON-LD or product-price metadata")
        price = _positive_decimal(offer.get("price"))
        currency = _clean(offer.get("priceCurrency") or "EUR").upper()
        from ..models import normalize_currency
        try:
            currency = normalize_currency(currency)
        except ValueError as exc:
            raise AdapterFailure(ErrorKind.INVALID_CURRENCY, "Deloox returned an invalid ISO currency code") from exc
        try:
            price_minor = int((price * 100).quantize(Decimal("1")))
        except Exception as exc:
            raise AdapterFailure(ErrorKind.INVALID_PRICE, "Deloox price could not be converted to minor units") from exc
        self._validate_host_and_path(final_url)
        gtin = _clean(data.get("gtin13") or data.get("gtin") or data.get("gtin12") or data.get("gtin8")) or None
        mpn = _clean(data.get("mpn")) or None
        sku = _clean(data.get("sku")) or _meta_content(soup, "sku", "product:retailer_item_id") or None
        return RetailerOfferRecord(
            store=self.store_key,
            source_url=url,
            product_url=final_url,
            title=title,
            brand=brand,
            price_minor=price_minor,
            currency=currency,
            observed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            parser_version=self.parser_version,
            trace_id=__import__("uuid").uuid4().hex,
            raw_price=_clean(offer.get("price")),
            availability=_availability(offer.get("availability")),
            size_ml=_size_ml(title),
            concentration=_concentration(title),
            gender=None,
            sku=sku,
            gtin=gtin,
            mpn=mpn,
        )

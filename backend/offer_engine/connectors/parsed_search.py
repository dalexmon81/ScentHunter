"""Adapter for existing retailer-specific search-stream parsers.

Each retailer keeps its own discovery and product-page parsing logic. This
adapter only translates the already-parsed row into Offer Engine contracts;
it never assigns canonical IDs or upgrades unknown stock to in-stock.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

import requests

from ..adapters import ConnectorHealth
from ..contracts import Availability, OfferObservation, RetailerListing, Verification


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, Mapping) else value


def _positive_size(value: Any) -> int | None:
    value = _field_value(value)
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        return None
    return int(number)


def _price(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip().replace("\\u00a0", " ")
    raw = re.sub(r"[^0-9,.-]", "", raw)
    if not raw:
        return None
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[1]
        raw = raw.replace(",", ".") if len(tail) in (1, 2) else raw.replace(",", "")
    try:
        result = Decimal(raw)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result > 0 else None


def _availability(value: Any) -> Availability:
    raw = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if raw in {
        "out_of_stock", "outofstock", "sold_out", "soldout", "unavailable",
        "not_available", "niet_op_voorraad", "uitverkocht", "rupture_de_stock",
    }:
        return Availability.OUT_OF_STOCK
    if raw in {
        "in_stock", "instock", "available", "in_stock_available",
        "op_voorraad", "add_to_cart",
    }:
        return Availability.IN_STOCK
    return Availability.UNKNOWN


class ParsedSearchConnector:
    """Translate one retailer's verified search-stream results into observations."""

    def __init__(
        self,
        retailer: str,
        module_name: str,
        market: str,
        *,
        scraper: Any | None = None,
    ):
        self.retailer = retailer.strip().lower()
        self.module_name = module_name
        self.market = market.strip().upper()
        self._scraper = scraper
        self._rows: dict[str, Mapping[str, Any]] = {}
        if not self.retailer or not self.market:
            raise ValueError("retailer and market are required")

    def _module(self):
        if self._scraper is not None:
            return self._scraper
        try:
            self._scraper = importlib.import_module(self.module_name)
        except ModuleNotFoundError as exc:
            if not self.module_name.startswith("scrapers."):
                raise
            fallback = "backend." + self.module_name
            try:
                self._scraper = importlib.import_module(fallback)
            except ModuleNotFoundError:
                raise exc
        return self._scraper

    def discover(self, query: str) -> Iterable[RetailerListing]:
        query = str(query or "").strip()
        if not query:
            return []
        scraper = self._module()
        search_stream = getattr(scraper, "search_stream", None)
        if not callable(search_stream):
            raise RuntimeError(f"{self.retailer}_search_stream_unavailable")
        result = search_stream(query)
        if (
            not isinstance(result, Mapping)
            or result.get("status") not in {"success", "partial"}
            or result.get("verified") is not True
        ):
            status = result.get("status", "invalid_result") if isinstance(result, Mapping) else "invalid_result"
            details = result.get("details", {}) if isinstance(result, Mapping) else {}
            raise RuntimeError(f"{self.retailer}_discovery_{status}:{details}")

        listings = []
        self._rows = {}
        seen = set()
        for raw in result.get("results") or []:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            title = str(row.get("name") or row.get("title") or row.get("product_name") or "").strip()
            brand = str(row.get("brand") or row.get("product_brand") or "").strip()
            base_url = str(getattr(scraper, "BASE_URL", "") or "").strip()
            raw_url = str(row.get("url") or row.get("product_url") or row.get("link") or "").strip()
            url = urljoin(base_url.rstrip("/") + "/", raw_url) if raw_url else ""
            parsed = urlparse(url)
            base_host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
            host = (parsed.hostname or "").lower().removeprefix("www.")
            if (
                not title or not url or parsed.scheme not in {"http", "https"}
                or not host or (base_host and host != base_host and not host.endswith("." + base_host))
            ):
                continue

            attrs = _mapping(row.get("attributes"))
            identity = _mapping(row.get("identity"))
            size_value = attrs.get("size_ml", row.get("size_ml"))
            size_ml = _positive_size(size_value)
            concentration = _field_value(attrs.get("concentration", row.get("concentration")))
            sku = _field_value(identity.get("sku", row.get("sku")))
            gtin = _field_value(identity.get("gtin", row.get("gtin") or row.get("ean")))
            external_id = str(sku or gtin or hashlib.sha256(
                f"{url}|{size_ml or ''}|{title}".encode("utf-8")
            ).hexdigest()[:24]).strip()
            if external_id in seen:
                continue
            seen.add(external_id)
            listing = RetailerListing(
                retailer=self.retailer,
                external_id=external_id,
                product_url=url,
                raw_title=title,
                raw_brand=brand or None,
                raw_size_ml=size_ml,
                raw_concentration=str(concentration).strip() if concentration else None,
                raw_gtin=str(gtin).strip() if gtin else None,
                market=self.market,
            )
            self._rows[external_id] = row
            listings.append(listing)
        return listings

    def observe(self, listing: RetailerListing) -> OfferObservation:
        if listing.retailer != self.retailer:
            raise ValueError("listing belongs to another retailer")
        row = self._rows.get(str(listing.external_id or ""))
        if row is None:
            raise RuntimeError(f"{self.retailer}_listing_not_in_current_discovery")
        url = str(row.get("url") or row.get("product_url") or row.get("link") or "").strip()
        scraper = self._module()
        base_url = str(getattr(scraper, "BASE_URL", "") or "").strip()
        url = urljoin(base_url.rstrip("/") + "/", url) if url else ""
        if url != listing.product_url:
            raise ValueError(f"{self.retailer}_listing_url_changed")

        attrs = _mapping(row.get("attributes"))
        identity = _mapping(row.get("identity"))
        offer = _mapping(row.get("offer"))
        availability = _availability(
            offer.get("availability", row.get("availability"))
        )
        raw_price = offer.get("price")
        if raw_price is None:
            raw_price = row.get("price_num", row.get("price"))
        price = _price(raw_price)
        if availability is Availability.OUT_OF_STOCK:
            price = None
        currency = str(offer.get("currency") or row.get("currency") or "EUR").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            currency = "EUR"
        evidence = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()

        size = _positive_size(attrs.get("size_ml", row.get("size_ml")))
        concentration = _field_value(attrs.get("concentration", row.get("concentration")))
        gtin = _field_value(identity.get("gtin", row.get("gtin") or row.get("ean")))
        sku = _field_value(identity.get("sku", row.get("sku")))
        page = {
            "name": listing.raw_title,
            "brand": listing.raw_brand,
            "attributes": {
                "size_ml": {"value": size} if size is not None else {},
                "concentration": {"value": concentration} if concentration else {},
            },
            "identity": {
                "gtin": {"value": gtin} if gtin else {},
                "sku": {"value": sku} if sku else {},
            },
            "raw_data": _mapping(row.get("raw_data")),
        }
        return OfferObservation.now(
            listing_key=f"{self.retailer}:{listing.external_id}",
            price=price,
            currency=currency,
            availability=availability,
            source="product_page",
            verification=Verification.UNVERIFIED,
            evidence_url=listing.product_url,
            evidence_hash=digest,
            raw_payload={"retailer": self.retailer, "parsed_page": page, "search_row": row},
        )

    def healthcheck(self) -> ConnectorHealth:
        scraper = self._module()
        base_url = str(getattr(scraper, "BASE_URL", "") or "").strip()
        if not base_url:
            return ConnectorHealth(self.retailer, False, "product_page", "base_url_missing")
        try:
            response = requests.get(base_url, timeout=(3.5, 8.0), allow_redirects=True)
            sample = str(getattr(response, "text", "") or "")[:20000].lower()
            challenged = "client challenge" in sample or "cf-chl-" in sample or "challenge-platform" in sample
            ok = 200 <= response.status_code < 400 and not challenged
            message = "client_challenge" if challenged else f"HTTP {response.status_code}"
            return ConnectorHealth(self.retailer, ok, "product_page", message)
        except requests.RequestException as exc:
            return ConnectorHealth(self.retailer, False, "product_page", type(exc).__name__)

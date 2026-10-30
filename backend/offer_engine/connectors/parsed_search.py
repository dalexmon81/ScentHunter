"""Adapter for retailer discovery plus independent product-detail verification.

Search results identify candidate URLs only. Every offer fact persisted by this
adapter is fetched again from the exact retailer product page (or authorized
store product JSON endpoint); search snippets are retained for diagnostics
but never used as price, stock, or variant evidence.
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



def _normalise_product_page(scraper: Any, retailer: str, listing: RetailerListing, session: requests.Session) -> Mapping[str, Any]:
    """Fetch and parse the exact retailer product URL; search snippets are never offer evidence."""
    if retailer == "parfumcity":
        product_json = getattr(scraper, "product_json", None)
        make_item = getattr(scraper, "make_item", None)
        if not callable(product_json) or not callable(make_item):
            raise RuntimeError("parfumcity_product_page_parser_unavailable")
        product = product_json(session, listing.product_url)
        if not isinstance(product, Mapping):
            raise RuntimeError("parfumcity_product_page_unavailable")
        candidates = []
        for variant in product.get("variants") or []:
            if not isinstance(variant, Mapping):
                continue
            parsed = make_item(product, variant, listing.product_url, listing.raw_title)
            if isinstance(parsed, Mapping):
                candidates.append(parsed)
        wanted_sku = str(listing.external_id or "")
        wanted_size = listing.raw_size_ml
        exact = [
            item for item in candidates
            if (
                str(_field_value(_mapping(item.get("identity")).get("sku")) or "") == wanted_sku
                or (
                    wanted_size is not None
                    and _positive_size(_mapping(item.get("attributes")).get("size_ml")) == wanted_size
                )
            )
        ]
        if len(exact) != 1:
            raise RuntimeError("parfumcity_product_variant_not_uniquely_verified")
        return exact[0]

    if retailer == "bplatz":
        parser = getattr(scraper, "product_from_page", None)
        if not callable(parser):
            raise RuntimeError("bplatz_product_page_parser_unavailable")
        result = parser(session, listing.product_url, listing.raw_title)
    else:
        parser = getattr(scraper, "extract_product_page", None)
        if not callable(parser):
            raise RuntimeError(f"{retailer}_product_page_parser_unavailable")
        if retailer == "easycosmetic":
            result = parser(session, listing.product_url)
        elif retailer == "sabina":
            result = parser(session, listing.product_url, listing.raw_title, authoritative_search=True)
        elif retailer == "orioudh":
            # The Shopify product JSON endpoint is already tied to this exact
            # discovered URL; derive its identity from the URL, not search text.
            result = parser(session, listing.product_url, "")
        else:
            result = parser(session, listing.product_url, listing.raw_title)

    if isinstance(result, list):
        expected_size = listing.raw_size_ml
        expected_id = str(listing.external_id or "")
        matches = []
        for item in result:
            if not isinstance(item, Mapping):
                continue
            attrs = _mapping(item.get("attributes"))
            identity = _mapping(item.get("identity"))
            size = _positive_size(attrs.get("size_ml", item.get("size_ml")))
            ids = {
                str(_field_value(identity.get(key)) or "")
                for key in ("sku", "gtin", "store_variant_id", "store_product_id")
            }
            if (expected_size is None or size == expected_size) and (expected_id in ids or (expected_size is not None and size == expected_size)):
                matches.append(item)
        if len(matches) != 1:
            raise RuntimeError(f"{retailer}_product_variant_not_uniquely_verified")
        result = matches[0]
    if not isinstance(result, Mapping):
        raise RuntimeError(f"{retailer}_product_page_unavailable")

    if retailer == "sabina":
        # Sabina's variant selector is client-side: the HTTP request does not
        # transmit the URL fragment. Never trust the parent page's selected
        # offer for every size. Bind this listing to its exact variant record.
        variants = [item for item in result.get("variants") or [] if isinstance(item, Mapping)]
        requested_url = listing.product_url
        url_matches = [
            item for item in variants
            if str(item.get("url") or "").strip() == requested_url
        ]
        candidates = url_matches
        if not candidates and listing.raw_size_ml is not None:
            size_matches = [
                item for item in variants
                if _positive_size(item.get("size_ml")) == listing.raw_size_ml
            ]
            candidates = size_matches
        if len(candidates) != 1:
            raise RuntimeError("sabina_product_variant_not_uniquely_verified")
        variant = candidates[0]
        selected = dict(result)
        selected["url"] = str(variant.get("url") or requested_url)
        selected["attributes"] = dict(_mapping(result.get("attributes")))
        selected["attributes"]["size_ml"] = {"value": variant.get("size_ml")}
        selected["offer"] = {
            "price": variant.get("price_num"),
            "currency": variant.get("currency") or "EUR",
            "availability": variant.get("availability") or "unknown",
        }
        selected["identity"] = dict(_mapping(result.get("identity")))
        if variant.get("sku"):
            selected["identity"]["sku"] = {"value": variant.get("sku")}
        if variant.get("gtin"):
            selected["identity"]["gtin"] = {"value": variant.get("gtin")}
        return selected

    return result


def _page_facts(scraper: Any, retailer: str, listing: RetailerListing, session: requests.Session) -> dict[str, Any]:
    page = _normalise_product_page(scraper, retailer, listing, session)
    source = _mapping(page.get("source"))
    provenance = _mapping(page.get("provenance"))
    attributes = _mapping(page.get("attributes"))
    identity = _mapping(page.get("identity"))
    offer = _mapping(page.get("offer"))

    page_url = str(
        page.get("url") or source.get("url") or provenance.get("source_page") or listing.product_url
    ).strip()
    expected_host = (urlparse(listing.product_url).hostname or "").lower().removeprefix("www.")
    actual = urlparse(page_url)
    actual_host = (actual.hostname or "").lower().removeprefix("www.")
    if actual.scheme not in {"http", "https"} or actual_host != expected_host:
        raise RuntimeError(f"{retailer}_product_page_redirected_outside_storefront")
    if actual.path.rstrip("/") != urlparse(listing.product_url).path.rstrip("/"):
        raise RuntimeError(f"{retailer}_product_page_redirected_to_different_product")

    name = str(page.get("name") or page.get("title") or source.get("source_name") or "").strip()
    if not name:
        raise RuntimeError(f"{retailer}_product_page_missing_product_title")
    brand = str(page.get("brand") or source.get("source_brand") or "").strip() or None
    size = _positive_size(attributes.get("size_ml")) or _positive_size(page.get("size_ml"))
    concentration = _field_value(attributes.get("concentration")) or _field_value(page.get("concentration"))
    gtin = _field_value(identity.get("gtin")) or page.get("gtin") or page.get("ean")
    sku = _field_value(identity.get("sku")) or page.get("sku")
    price = offer.get("price")
    if price is None:
        price = page.get("price_num")
    if price is None:
        price = page.get("price")
    availability = offer.get("availability")
    if availability is None:
        availability = page.get("availability")
    currency = offer.get("currency") or page.get("currency") or "EUR"

    # These values are all taken from the fetched product detail, never the
    # search-result row. Missing page facts remain missing and fail closed.
    return {
        "name": name,
        "brand": brand,
        "url": page_url,
        "attributes": {
            "size_ml": {"value": size} if size is not None else {},
            "concentration": {"value": concentration} if concentration else {},
        },
        "identity": {
            "gtin": {"value": gtin} if gtin else {},
            "sku": {"value": sku} if sku else {},
        },
        "offer": {
            "price": price,
            "currency": currency,
            "availability": availability,
        },
        "raw_data": dict(page),
    }


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
            store_variant_id = _field_value(identity.get("store_variant_id"))
            base_external_id = str(store_variant_id or sku or gtin or hashlib.sha256(
                f"{url}|{size_ml or ''}|{title}".encode("utf-8")
            ).hexdigest()[:24]).strip()
            external_id = base_external_id
            if external_id in seen:
                # Product-level SKUs are sometimes reused across bottle sizes.
                # Keep sibling sellable variants as independent retailer listings.
                suffix = str(gtin or size_ml or hashlib.sha256(url.encode("utf-8")).hexdigest()[:10])
                external_id = f"{base_external_id}:{suffix}"
            if external_id in seen:
                external_id = f"{base_external_id}:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]}"
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

        scraper = self._module()
        with requests.Session() as session:
            page = _page_facts(scraper, self.retailer, listing, session)

        availability = _availability(_mapping(page.get("offer")).get("availability"))
        price = _price(_mapping(page.get("offer")).get("price"))
        if availability is Availability.OUT_OF_STOCK:
            price = None
        currency = str(_mapping(page.get("offer")).get("currency") or "EUR").upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            currency = "EUR"

        evidence = json.dumps(page, ensure_ascii=False, sort_keys=True, default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        parsed_page = {
            "name": page.get("name"),
            "brand": page.get("brand"),
            "attributes": page.get("attributes") or {},
            "identity": page.get("identity") or {},
            "raw_data": page.get("raw_data") or {},
        }
        return OfferObservation.now(
            listing_key=f"{self.retailer}:{listing.external_id}",
            price=price,
            currency=currency,
            availability=availability,
            source="product_page",
            verification=Verification.UNVERIFIED,
            evidence_url=str(page.get("url") or listing.product_url),
            evidence_hash=digest,
            raw_payload={
                "retailer": self.retailer,
                "parsed_page": parsed_page,
                "search_row": row,
                "evidence_source": "fetched_product_detail",
            },
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

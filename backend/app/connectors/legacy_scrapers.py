"""Adapters that preserve the proven legacy retailer parsers behind the async contract.

Discovery is an operator-configured background catalog task. It never runs from
a user search request. The legacy parsers remain the source of retailer-specific
HTML interpretation; this layer only adapts their output and enforces provenance.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import requests

from app.connectors.base import ConnectorUnavailable, DiscoveredProduct, StoreConnector

STORE_SLUGS = {
    "bplatz": "bplatz",
    # ScentHunter currently supports only the Belgian Deloox storefront.
    "deloox-be": "deloox",
    "sabina-es": "sabina",
    "easycosmetic-de": "easycosmetic",
    "parfumzentrum-de": "parfumzentrum",
}

SCRAPER_MODULES = {
    "bplatz": "scrapers.bplatz.scraper",
    "deloox": "scrapers.deloox.scraper",
    "sabina": "scrapers.sabina.scraper",
    "easycosmetic": "scrapers.easycosmetic.scraper",
    "parfumzentrum": "scrapers.parfumzentrum.scraper",
}


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _identity_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, Mapping) else value


def _jsonld_has_currency(value: Any) -> bool:
    if isinstance(value, Mapping):
        if isinstance(value.get("priceCurrency"), str) and len(value["priceCurrency"].strip()) == 3:
            return True
        return any(_jsonld_has_currency(child) for child in value.values())
    if isinstance(value, list):
        return any(_jsonld_has_currency(child) for child in value)
    return False


def _price_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("€", "").replace("EUR", "").replace(" ", "").strip()
        if "," in value and "." in value:
            if value.rfind(",") > value.rfind("."):
                value = value.replace(".", "").replace(",", ".")
            else:
                value = value.replace(",", "")
        elif "," in value:
            value = value.replace(",", ".")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _availability(raw: Mapping[str, Any]) -> str | None:
    value = _nested(raw, "offer", "availability") or raw.get("availability")
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"in_stock", "instock", "available", "true", "auf_lager", "lieferbar"}:
            return "in_stock"
        if normalized in {"out_of_stock", "outofstock", "sold_out", "soldout", "unavailable", "false", "ausverkauft"}:
            return "out_of_stock"
    available = raw.get("available")
    if isinstance(available, bool):
        return "in_stock" if available else "out_of_stock"
    return None


class LegacyScraperConnector(StoreConnector):
    """Thin adapter around one existing scraper module; no scraper rewrite."""

    def __init__(self, store_key: str, scraper_module: Any | None = None, *, cache_ttl_seconds: int = 900):
        if store_key not in SCRAPER_MODULES:
            raise ValueError(f"unsupported legacy scraper: {store_key}")
        self.store_key = store_key
        super().__init__()
        if scraper_module is None:
            from importlib import import_module
            scraper_module = import_module(SCRAPER_MODULES[store_key])
        self._scraper = scraper_module
        self._cache_ttl = cache_ttl_seconds
        self._cached_at = 0.0
        self._snapshot: tuple[dict[str, Any], ...] = ()
        self._snapshot_lock = asyncio.Lock()

    def _queries(self) -> tuple[str, ...]:
        key = f"SCENTHUNTER_DISCOVERY_QUERIES_{self.store_key.upper()}"
        raw = os.environ.get(key, "")
        queries = tuple(dict.fromkeys(item.strip() for item in raw.split(";") if item.strip()))
        if not queries:
            raise ValueError(f"{key} must contain semicolon-separated operator-approved discovery queries")
        return queries

    def _search_snapshot(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        search_stream = getattr(self._scraper, "search_stream", None)
        search = getattr(self._scraper, "search", None)
        for query in self._queries():
            try:
                if callable(search_stream):
                    report = search_stream(query)
                    if not isinstance(report, Mapping):
                        raise ConnectorUnavailable(f"{self.store_key} returned an invalid search report")
                    status = str(report.get("status") or "").lower()
                    details = report.get("details") if isinstance(report.get("details"), Mapping) else {}
                    if status in {"timeout", "unavailable", "blocked", "error"} or details.get("technical_failure"):
                        raise ConnectorUnavailable(f"{self.store_key} discovery failed: {report.get('error') or status}")
                    batch = report.get("results") or []
                elif callable(search):
                    batch = search(query)
                else:
                    raise RuntimeError(f"{self.store_key} scraper has no search function")
            except ConnectorUnavailable:
                raise
            except (requests.Timeout, requests.ConnectionError, requests.RequestException) as exc:
                raise ConnectorUnavailable(f"{self.store_key} discovery request failed: {type(exc).__name__}: {exc}") from exc
            if not isinstance(batch, Sequence) or isinstance(batch, (str, bytes)):
                raise ConnectorUnavailable(f"{self.store_key} returned malformed discovery results")
            for row in batch:
                if not isinstance(row, Mapping):
                    continue
                url = self._product_url(row)
                if not url:
                    continue
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    continue
                if len(url) > 240:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                record = dict(row)
                record["external_product_id"] = url
                record["product_url"] = url
                rows.append(record)
        return tuple(rows)

    @staticmethod
    def _product_url(raw: Mapping[str, Any]) -> str:
        return str(raw.get("url") or _nested(raw, "source", "url") or _nested(raw, "source", "source_url") or "").strip()

    async def _get_snapshot(self, *, force: bool = False) -> tuple[dict[str, Any], ...]:
        if not force and self._snapshot and time.monotonic() - self._cached_at < self._cache_ttl:
            return self._snapshot
        async with self._snapshot_lock:
            if not force and self._snapshot and time.monotonic() - self._cached_at < self._cache_ttl:
                return self._snapshot
            try:
                snapshot = await asyncio.to_thread(self._search_snapshot)
            except (ConnectorUnavailable, ValueError):
                # Missing operator-approved seed queries are configuration errors,
                # not retailer outages. Do not count them toward connector quarantine.
                raise
            except Exception as exc:
                raise ConnectorUnavailable(f"{self.store_key} discovery failed: {type(exc).__name__}: {exc}") from exc
            self._snapshot = snapshot
            self._cached_at = time.monotonic()
            return snapshot

    async def discover_products(self, *, cursor: str | None = None, limit: int = 100) -> Sequence[DiscoveredProduct]:
        if isinstance(limit, bool) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            offset = int(cursor or "0")
        except (TypeError, ValueError):
            raise ValueError("cursor must be a non-negative integer") from None
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer")
        snapshot = await self._get_snapshot()
        return tuple(
            DiscoveredProduct(
                external_product_id=row["external_product_id"],
                product_url=row["product_url"],
                raw_payload=row,
            )
            for row in snapshot[offset:offset + limit]
        )

    def _fetch_product_sync(self, url: str) -> Mapping[str, Any] | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("external_product_id must be an absolute product URL")
        session = requests.Session()
        try:
            parser = getattr(self._scraper, "extract_product_page", None)
            if self.store_key == "easycosmetic":
                if not callable(parser):
                    parser = getattr(self._scraper, "parse_product", None)
                    return parser(url) if callable(parser) else None
                return parser(session, url, slug="")
            if not callable(parser):
                raise RuntimeError(f"{self.store_key} scraper has no product-page parser")
            if self.store_key == "sabina":
                return parser(session, url, query="", authoritative_search=True)
            return parser(session, url, query="")
        except (requests.Timeout, requests.ConnectionError, requests.RequestException) as exc:
            raise ConnectorUnavailable(f"{self.store_key} product fetch failed: {type(exc).__name__}: {exc}") from exc
        finally:
            session.close()

    async def fetch_product(self, external_product_id: str) -> Mapping[str, Any] | None:
        url = str(external_product_id or "").strip()
        if not url:
            raise ValueError("external_product_id is required")
        try:
            record = await asyncio.to_thread(self._fetch_product_sync, url)
        except ConnectorUnavailable:
            raise
        except Exception as exc:
            request_error = getattr(self._scraper, "StoreRequestError", ())
            if request_error and isinstance(exc, request_error):
                raise ConnectorUnavailable(
                    f"{self.store_key} product endpoint unavailable: {type(exc).__name__}: {exc}"
                ) from exc
            raise
        if isinstance(record, Mapping):
            enriched = dict(record)
            enriched.setdefault("external_product_id", url)
            enriched.setdefault("product_url", self._product_url(record) or url)
            enriched.setdefault("url", self._product_url(record) or url)
            return enriched
        return record

    async def fetch_offers(self, product_key: str) -> Sequence[Mapping[str, Any]]:
        record = await self.fetch_product(product_key)
        return (record,) if isinstance(record, Mapping) else ()

    async def fetch_price_and_stock(self, offer_id: str) -> Mapping[str, Any]:
        record = await self.fetch_product(offer_id)
        if not isinstance(record, Mapping):
            raise LookupError(f"{self.store_key}_product_not_found")
        parsed = self.parse_raw(record)
        return {
            "external_product_id": str(offer_id),
            "product_url": parsed["product_url"],
            "url": parsed["product_url"],
            "price": parsed["price"],
            "currency": parsed["currency"],
            "currency_explicit": parsed["currency_explicit"],
            "availability": parsed["availability"],
            "captured_at": time.time(),
            "source": f"{self.store_key}_legacy_scraper",
            "raw_record": dict(record),
        }

    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(raw, Mapping):
            raise TypeError("raw must be a mapping")
        offer = raw.get("offer") if isinstance(raw.get("offer"), Mapping) else {}
        source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
        attributes = raw.get("attributes") if isinstance(raw.get("attributes"), Mapping) else {}
        identity = raw.get("identity") if isinstance(raw.get("identity"), Mapping) else {}
        size = _identity_value(attributes.get("size_ml"))
        concentration = _identity_value(attributes.get("concentration"))
        raw_data = raw.get("raw_data") if isinstance(raw.get("raw_data"), Mapping) else {}
        jsonld = raw_data.get("jsonld") or raw_data.get("jsonld_product") or {}
        currency = str(offer.get("currency") or raw.get("currency") or "EUR").strip().upper()
        explicit_currency = raw.get("currency_explicit") is True or _jsonld_has_currency(jsonld)
        price = _price_decimal(offer.get("price") if offer.get("price") is not None else raw.get("price_num"))
        if price is None:
            price = _price_decimal(raw.get("price"))
        url = self._product_url(raw)
        return {
            "external_product_id": str(raw.get("external_product_id") or url),
            "raw_name": raw.get("name") or source.get("source_name") or source.get("name"),
            "brand_raw": raw.get("brand") or source.get("source_brand") or source.get("brand"),
            "size_ml": size if size is not None else raw.get("size_ml"),
            "concentration": concentration if concentration is not None else raw.get("concentration"),
            "gtin": _identity_value(identity.get("gtin")) or raw.get("gtin"),
            "sku": _identity_value(identity.get("sku")) or raw.get("sku"),
            "mpn": _identity_value(identity.get("mpn")) or raw.get("mpn"),
            "price": str(price) if price is not None else None,
            "currency": currency,
            "currency_explicit": explicit_currency,
            "availability": _availability(raw),
            "product_url": url,
            "url": url,
            "image_url": raw.get("image") or source.get("image"),
            "source": f"{self.store_key}_legacy_scraper",
            "raw_payload": dict(raw),
        }


def build_legacy_connector(store_key: str) -> LegacyScraperConnector:
    return LegacyScraperConnector(store_key)


def connector_key_for_store_slug(store_slug: str) -> str | None:
    return STORE_SLUGS.get(store_slug)

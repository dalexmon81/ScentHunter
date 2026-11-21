"""Fixture-friendly Bplatz adapter for the background Offer-First ingestion pipeline.

The existing scraper remains authoritative for retailer-specific discovery and HTML
parsing. This adapter performs no persistence and is never part of user search.
"""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import requests

from app.connectors.base import ConnectorUnavailable, DiscoveredProduct, StoreConnector


class BplatzConnector(StoreConnector):
    store_key = "bplatz"

    def __init__(self, scraper_module: Any | None = None) -> None:
        super().__init__()
        if scraper_module is None:
            from scrapers.bplatz import scraper as scraper_module
        self._scraper = scraper_module
        self._snapshot: tuple[str, ...] = ()
        self._cached_at = 0.0
        self._cache_ttl = 900

    @staticmethod
    def _is_store_product_url(url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        return (
            parsed.scheme == "https"
            and (host == "bplatz.de" or host.endswith(".bplatz.de"))
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and "/products/" in parsed.path.lower()
        )

    def _queries(self) -> tuple[str, ...]:
        values = os.environ.get("SCENTHUNTER_DISCOVERY_QUERIES_BPLATZ", "")
        queries = tuple(dict.fromkeys(v.strip() for v in values.split(";") if v.strip()))
        if not queries:
            raise ValueError("SCENTHUNTER_DISCOVERY_QUERIES_BPLATZ must contain operator-approved queries")
        return queries

    def _discover_sync(self) -> tuple[str, ...]:
        session = requests.Session()
        found: list[str] = []
        seen: set[str] = set()
        verified_any = False
        try:
            for query in self._queries():
                try:
                    urls, errors, verified = self._scraper.discover(session, query)
                except requests.RequestException as exc:
                    raise ConnectorUnavailable(f"Bplatz discovery request failed: {type(exc).__name__}") from exc
                verified_any = verified_any or bool(verified)
                for url in urls or ():
                    value = str(url or "").strip()
                    if self._is_store_product_url(value) and value not in seen:
                        seen.add(value)
                        found.append(value)
                if not verified and errors and not verified_any:
                    continue
            if not verified_any:
                raise ConnectorUnavailable("Bplatz discovery could not verify any discovery channel")
            return tuple(found)
        finally:
            session.close()

    async def discover_products(self, *, cursor: str | None = None, limit: int = 100) -> Sequence[DiscoveredProduct]:
        if isinstance(limit, bool) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            offset = int(cursor or "0")
        except (TypeError, ValueError):
            raise ValueError("cursor must be a non-negative integer") from None
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer")
        if not self._snapshot or time.monotonic() - self._cached_at >= self._cache_ttl:
            self._snapshot = await asyncio.to_thread(self._discover_sync)
            self._cached_at = time.monotonic()
        return tuple(
            DiscoveredProduct(url, url, {"discovery_source": "bplatz_scraper"})
            for url in self._snapshot[offset:offset + limit]
        )

    def _fetch_sync(self, url: str) -> Mapping[str, Any] | None:
        if not self._is_store_product_url(url):
            raise ValueError("external_product_id must be a Bplatz Shopify product URL")
        session = requests.Session()
        try:
            response = session.get(
                url, headers=getattr(self._scraper, "HEADERS", {}),
                timeout=getattr(self._scraper, "TIMEOUT", (2.5, 6.0)),
                allow_redirects=False,
            )
            try:
                if response.status_code >= 300:
                    raise ConnectorUnavailable(f"Bplatz product page returned HTTP {response.status_code}")
                if not self._is_store_product_url(response.url):
                    raise ConnectorUnavailable("Bplatz product page redirected outside the retailer domain")
                query = urlparse(response.url).path.rsplit("/products/", 1)[-1].replace("-", " ").strip()
                return self._scraper.parse_product_html(response.text, response.url, query)
            finally:
                response.close()
        except requests.RequestException as exc:
            raise ConnectorUnavailable(f"Bplatz product fetch failed: {type(exc).__name__}") from exc
        finally:
            session.close()

    async def fetch_product(self, external_product_id: str) -> Mapping[str, Any] | None:
        return await asyncio.to_thread(self._fetch_sync, str(external_product_id or "").strip())

    async def fetch_offers(self, product_key: str) -> Sequence[Mapping[str, Any]]:
        record = await self.fetch_product(product_key)
        return (record,) if isinstance(record, Mapping) else ()

    async def fetch_price_and_stock(self, offer_id: str) -> Mapping[str, Any]:
        raw = await self.fetch_product(offer_id)
        if not isinstance(raw, Mapping):
            raise LookupError("bplatz_product_not_found")
        parsed = self.parse_raw(raw)
        return {**parsed, "captured_at": time.time(), "raw_record": dict(raw)}

    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
        identity = raw.get("identity") if isinstance(raw.get("identity"), Mapping) else {}
        attributes = raw.get("attributes") if isinstance(raw.get("attributes"), Mapping) else {}
        offer = raw.get("offer") if isinstance(raw.get("offer"), Mapping) else {}
        def value(item: Any) -> Any:
            return item.get("value") if isinstance(item, Mapping) else item
        url = str(source.get("url") or raw.get("url") or "").strip()
        currency = str(offer.get("currency") or raw.get("currency") or "EUR").strip().upper()
        price = offer.get("price")
        if price is None:
            price = raw.get("price_num")
        return {
            "external_product_id": str(raw.get("external_product_id") or url),
            "raw_name": raw.get("name") or source.get("source_name"),
            "brand_raw": raw.get("brand") or source.get("source_brand"),
            "size_ml": value(attributes.get("size_ml")),
            "concentration": value(attributes.get("concentration")),
            "gtin": value(identity.get("gtin")),
            "sku": value(identity.get("sku")),
            "price": str(price) if price is not None else None,
            "currency": currency,
            "currency_explicit": offer.get("currency_explicit") is True or raw.get("currency_explicit") is True,
            "availability": offer.get("availability") or raw.get("availability"),
            "product_url": url,
            "url": url,
            "image_url": source.get("image") or raw.get("image"),
            "source": "bplatz_scraper",
            "raw_payload": dict(raw),
        }


def build_bplatz_connector() -> BplatzConnector:
    return BplatzConnector()

"""Fixture-friendly PerfumeMarket adapter for background Offer-First ingestion.

The existing retailer scraper remains responsible for discovery and page parsing.
Only JSON-LD priceCurrency evidence is promoted as explicit; its EUR fallback
remains unverified.
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


class PerfumeMarketConnector(StoreConnector):
    store_key = "perfumemarket"

    def __init__(self, scraper_module: Any | None = None, *, cache_ttl_seconds: int = 900) -> None:
        super().__init__()
        if scraper_module is None:
            from scrapers.perfumemarket import scraper as scraper_module
        self._scraper = scraper_module
        self._cache_ttl = cache_ttl_seconds
        self._cached_at = 0.0
        self._snapshot: tuple[str, ...] = ()
        self._lock = asyncio.Lock()

    def _queries(self) -> tuple[str, ...]:
        raw = os.environ.get("SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET", "")
        queries = tuple(dict.fromkeys(v.strip() for v in raw.split(";") if v.strip()))
        if not queries:
            raise ValueError("SCENTHUNTER_DISCOVERY_QUERIES_PERFUMEMARKET must contain operator-approved queries")
        return queries

    def _discover_sync(self) -> tuple[str, ...]:
        urls: list[str] = []
        seen: set[str] = set()
        verified_any = False
        for query in self._queries():
            try:
                report = self._scraper.search_stream(query)
            except requests.RequestException as exc:
                raise ConnectorUnavailable(f"PerfumeMarket discovery failed: {type(exc).__name__}") from exc
            if not isinstance(report, Mapping):
                raise ConnectorUnavailable("PerfumeMarket returned an invalid discovery report")
            status = str(report.get("status") or "").lower()
            details = report.get("details") if isinstance(report.get("details"), Mapping) else {}
            if status in {"timeout", "unavailable", "blocked", "error"} or details.get("technical_failure"):
                raise ConnectorUnavailable(f"PerfumeMarket discovery failed: {report.get('error') or status}")
            verified_any = verified_any or report.get("verified") is True
            rows = report.get("results") or ()
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise ConnectorUnavailable("PerfumeMarket returned malformed discovery results")
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                url = str(row.get("url") or "").strip()
                parsed = urlparse(url)
                if parsed.scheme in {"http", "https"} and parsed.netloc and "/products/" in parsed.path.lower() and url not in seen:
                    seen.add(url)
                    urls.append(url)
        if not verified_any:
            raise ConnectorUnavailable("PerfumeMarket discovery did not verify any query")
        return tuple(urls)

    async def _get_snapshot(self, *, force: bool = False) -> tuple[str, ...]:
        if not force and self._snapshot and time.monotonic() - self._cached_at < self._cache_ttl:
            return self._snapshot
        async with self._lock:
            if not force and self._snapshot and time.monotonic() - self._cached_at < self._cache_ttl:
                return self._snapshot
            snapshot = await asyncio.to_thread(self._discover_sync)
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
        return tuple(DiscoveredProduct(url, url, {"discovery_source": "perfumemarket_scraper"}) for url in snapshot[offset:offset + limit])

    def _fetch_sync(self, url: str) -> Mapping[str, Any] | None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or "/products/" not in parsed.path.lower():
            raise ValueError("external_product_id must be an absolute Shopify product URL")
        session = requests.Session()
        try:
            record = self._scraper.extract_product_page(session, url, "")
            return record if isinstance(record, Mapping) else None
        except requests.RequestException as exc:
            raise ConnectorUnavailable(f"PerfumeMarket product fetch failed: {type(exc).__name__}") from exc
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
            raise LookupError("perfumemarket_product_not_found")
        return {**self.parse_raw(raw), "captured_at": time.time(), "raw_record": dict(raw)}

    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        offer = raw.get("offer") if isinstance(raw.get("offer"), Mapping) else {}
        source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
        identity = raw.get("identity") if isinstance(raw.get("identity"), Mapping) else {}
        def identity_value(value: Any) -> Any:
            return value.get("value") if isinstance(value, Mapping) else value
        url = str(raw.get("url") or source.get("url") or "").strip()
        currency = str(offer.get("currency") or raw.get("currency") or "EUR").strip().upper()
        # Scraper currently defaults currency to EUR and does not expose whether
        # JSON-LD supplied priceCurrency. Never infer explicit provenance.
        explicit_currency = raw.get("currency_explicit") is True or offer.get("currency_explicit") is True
        currency_source = (
            offer.get("currency_source") or raw.get("currency_source")
            if explicit_currency else None
        )
        price = offer.get("price") if offer.get("price") is not None else raw.get("price_num", raw.get("price"))
        return {
            "external_product_id": str(raw.get("external_product_id") or url),
            "raw_name": raw.get("name") or source.get("name"),
            "brand_raw": raw.get("brand") or source.get("brand"),
            "gtin": identity_value(identity.get("gtin")) or raw.get("gtin"),
            "sku": identity_value(identity.get("sku")) or raw.get("sku"),
            "mpn": identity_value(identity.get("mpn")) or raw.get("mpn"),
            "price": str(price) if price is not None else None,
            "currency": currency,
            "currency_explicit": explicit_currency,
            "currency_source": currency_source,
            "availability": offer.get("availability") or raw.get("availability"),
            "product_url": url,
            "url": url,
            "image_url": raw.get("image") or source.get("image"),
            "source": "perfumemarket_scraper",
            "raw_payload": dict(raw),
        }


def build_perfumemarket_connector() -> PerfumeMarketConnector:
    return PerfumeMarketConnector()

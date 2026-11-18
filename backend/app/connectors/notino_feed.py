"""Notino.fr connector backed by the authorized CJ/VIV product feed.

The feed is a complete structured snapshot, not a per-SKU endpoint. This adapter
caches one parsed snapshot briefly so discovery and refresh calls in the same
worker cycle do not repeatedly download the large feed. The worker remains
responsible for scheduling, rate limits, persistence, and quarantine.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.connectors.base import DiscoveredProduct, StoreConnector
from scrapers.notino import affiliate_feed


class NotinoAffiliateFeedConnector(StoreConnector):
    store_key = "notino"

    def __init__(
        self,
        *,
        feed_loader: Callable[[], bytes] | None = None,
        cache_ttl_seconds: int = 900,
    ) -> None:
        super().__init__()
        if cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must not be negative")
        self._feed_loader = feed_loader or affiliate_feed._fetch_feed
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cached_at = 0.0
        self._snapshot: tuple[dict[str, Any], ...] = ()
        self._snapshot_lock = asyncio.Lock()

    @staticmethod
    def _to_record(offer: affiliate_feed.NotinoOffer) -> dict[str, Any]:
        return {
            "external_product_id": offer.external_id,
            "title": offer.title,
            "brand": offer.brand,
            "gtin": offer.gtin,
            "sku": offer.sku,
            "mpn": offer.mpn,
            "size_ml": offer.size_ml,
            "price": str(offer.price),
            "currency": offer.currency,
            "availability": offer.availability,
            "currency_explicit": bool(offer.currency),
            "product_url": offer.url,
            "url": offer.affiliate_url or offer.url,
            "affiliate_url": offer.affiliate_url,
            "image_url": offer.image,
            "concentration": offer.concentration,
            "raw_xml": offer.raw_xml,
            "source": "authorized_cj_viv_xml_feed",
        }

    async def _get_snapshot(self, *, force: bool = False) -> tuple[dict[str, Any], ...]:
        now = time.monotonic()
        if (
            not force
            and self._snapshot
            and now - self._cached_at < self._cache_ttl_seconds
        ):
            return self._snapshot

        async with self._snapshot_lock:
            now = time.monotonic()
            if (
                not force
                and self._snapshot
                and now - self._cached_at < self._cache_ttl_seconds
            ):
                return self._snapshot

            payload = await asyncio.to_thread(self._feed_loader)
            offers = await asyncio.to_thread(affiliate_feed.parse_feed, payload)
            snapshot = tuple(self._to_record(item) for item in offers)
            self._snapshot = snapshot
            self._cached_at = time.monotonic()
            return snapshot

    async def refresh_snapshot(self) -> int:
        """Force one feed download at the start of a scheduled ingestion cycle."""
        return len(await self._get_snapshot(force=True))

    async def discover_products(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> Sequence[DiscoveredProduct]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            offset = int(cursor or "0")
        except (TypeError, ValueError):
            raise ValueError("cursor must be a non-negative integer") from None
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer")

        snapshot = await self._get_snapshot()
        page = snapshot[offset : offset + limit]
        return tuple(
            DiscoveredProduct(
                external_product_id=str(row["external_product_id"]),
                product_url=str(row["product_url"]),
                raw_payload=row,
            )
            for row in page
        )

    async def fetch_product(self, external_product_id: str) -> Mapping[str, Any] | None:
        key = str(external_product_id or "").strip()
        if not key:
            return None
        for row in await self._get_snapshot():
            if row["external_product_id"] == key:
                return row
        return None

    async def fetch_offers(self, product_key: str) -> Sequence[Mapping[str, Any]]:
        key = str(product_key or "").strip()
        if not key:
            return ()
        snapshot = await self._get_snapshot()
        return tuple(
            row for row in snapshot
            if row["external_product_id"] == key or row["product_url"] == key
        )

    async def fetch_price_and_stock(self, offer_id: str) -> Mapping[str, Any]:
        row = await self.fetch_product(offer_id)
        if row is None:
            raise LookupError("notino_offer_not_found_in_latest_feed_snapshot")
        return {
            "external_product_id": row["external_product_id"],
            "product_url": row["product_url"],
            "url": row["url"],
            "price": row["price"],
            "currency": row["currency"],
            "availability": row["availability"],
            "captured_at": time.time(),
            "source": row["source"],
            "raw_xml": row["raw_xml"],
        }

    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Map one feed record to the shared normalizer/persistence field names."""
        if not isinstance(raw, Mapping):
            raise TypeError("raw must be a mapping")
        return {
            "raw_name": raw.get("title"),
            "brand_raw": raw.get("brand"),
            "size_ml": raw.get("size_ml"),
            "concentration": raw.get("concentration"),
            "price": raw.get("price"),
            "currency": raw.get("currency"),
            "availability": raw.get("availability"),
            "product_url": raw.get("product_url"),
            "url": raw.get("url"),
            "external_product_id": raw.get("external_product_id"),
            "gtin": raw.get("gtin"),
            "sku": raw.get("sku"),
            "mpn": raw.get("mpn"),
            "image_url": raw.get("image_url"),
            "source": raw.get("source", "authorized_cj_viv_xml_feed"),
            "currency_explicit": raw.get("currency_explicit") is True,
            "raw_payload": {
                "raw_xml": raw.get("raw_xml"),
                "affiliate_url": raw.get("affiliate_url"),
            },
        }

"""Notino adapter backed by the authorized CJ/VIV XML affiliate feed.

This adapter is deliberately side-effect free: it parses feed evidence into the
universal connector contract and never persists to the legacy or canonical DB.
The worker/orchestrator owns persistence and quarantine policy.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Sequence

from app.connectors.base import OfferRecord, validate_offer
from app.services.product_normalization import normalize_product
from scrapers.notino import affiliate_feed


class NotinoAffiliateFeedConnector:
    store_key = "notino"
    source_kind = "authorized_affiliate_xml"

    def __init__(self, feed_loader: Callable[[], bytes | Awaitable[bytes]] | None = None):
        self._feed_loader = feed_loader
        self._offers: tuple[OfferRecord, ...] = ()
        self._raw_artifacts: list[dict[str, Any]] = []
        self._last_raw_feed: bytes | None = None

    async def _load_bytes(self) -> bytes:
        if self._feed_loader is None:
            payload = await asyncio.to_thread(affiliate_feed._fetch_feed)
        else:
            payload = self._feed_loader()
            if hasattr(payload, "__await__"):
                payload = await payload
        if not isinstance(payload, (bytes, bytearray)):
            raise affiliate_feed.FeedImportError("notino_feed_loader_must_return_bytes")
        self._last_raw_feed = bytes(payload)
        return self._last_raw_feed

    def raw_evidence_for(self, external_id: str | None = None):
        """Return the exact source XML feed bytes for durable raw capture."""
        return self._last_raw_feed

    def parse_raw(self, raw: bytes) -> Sequence[OfferRecord]:
        parsed = affiliate_feed.parse_feed(raw)
        captured_at = datetime.now(timezone.utc).isoformat()
        records: list[OfferRecord] = []
        for item in parsed:
            try:
                identity = normalize_product(
                    item.brand,
                    item.title,
                    concentration=item.concentration,
                    size_ml=item.size_ml,
                )
            except ValueError:
                # Ambiguous identity is not silently published by this adapter.
                continue
            records.append(OfferRecord(
                store=self.store_key,
                external_product_id=item.external_id,
                brand=item.brand,
                fragrance=identity.fragrance_name,
                concentration=identity.concentration,
                size_ml=identity.size_ml,
                gtin=item.gtin,
                title=item.title,
                url=item.url,
                price=Decimal(str(item.price)),
                currency=item.currency,
                availability=item.availability,
                captured_at=captured_at,
                source=self.source_kind,
                external_offer_id=item.external_id,
            ))
        return tuple(records)

    def validate_offer(self, offer: OfferRecord) -> tuple[bool, tuple[str, ...]]:
        return validate_offer(offer)

    async def discover_products(self) -> Sequence[dict]:
        raw = await self._load_bytes()
        self._raw_artifacts = [{"format": "xml", "content_type": "application/xml", "data": raw}]
        self._offers = tuple(self.parse_raw(raw))
        return tuple({
            "externalProductId": offer.external_product_id,
            "title": offer.title,
            "url": offer.url,
            "store": self.store_key,
        } for offer in self._offers)

    async def fetch_product(self, external_id: str) -> dict | None:
        if not self._offers:
            await self.discover_products()
        for offer in self._offers:
            if offer.external_product_id == str(external_id):
                return offer.to_dict()
        return None

    async def fetch_offers(self, product_key: str) -> Sequence[OfferRecord]:
        if not self._offers:
            await self.discover_products()
        key = str(product_key)
        return tuple(
            offer for offer in self._offers
            if offer.external_product_id == key or offer.url == key
        )

    async def fetch_price_and_stock(self, offer_id: str) -> OfferRecord | None:
        # A feed refresh is the authoritative price/stock refresh mechanism.
        # Reloading it avoids scraping a product page or fabricating stock.
        await self.discover_products()
        for offer in self._offers:
            if offer.external_offer_id == str(offer_id):
                return offer
        return None

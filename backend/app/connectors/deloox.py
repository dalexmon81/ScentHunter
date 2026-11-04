"""Deloox adapter over the existing retailer parser.

Deloox is HTML/JSON-LD backed, so this adapter is deliberately lower priority
than structured feeds. The existing parser remains the source of truth for
retailer-specific page validation; this module only maps its output into the
shared connector contract. Browser fallback is not enabled by this adapter.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence

from app.connectors.base import OfferRecord, RateLimiter, capture_raw_page_artifact, validate_offer
from app.services.product_normalization import normalize_product
from scrapers.deloox import scraper


class DelooxConnector:
    store_key = "deloox"
    source_kind = "jsonld_or_html"

    def __init__(self, discovery_terms: Sequence[str] = (), *, search_func: Callable | None = None,
                 page_loader: Callable[[str], Any] | None = None):
        self.discovery_terms = tuple(x.strip() for x in discovery_terms if x and x.strip())
        self._search = search_func or scraper.search
        self._page_loader = page_loader
        self._limiter = RateLimiter(0.5)
        self._offers: dict[str, OfferRecord] = {}
        self._raw_artifacts: list[dict[str, Any]] = []

    @staticmethod
    def _map_product(item: dict[str, Any]) -> OfferRecord | None:
        if not isinstance(item, dict):
            return None
        title = str(item.get("name") or item.get("source", {}).get("source_name") or "").strip()
        brand = str(item.get("brand") or item.get("source", {}).get("source_brand") or "").strip()
        url = str(item.get("url") or item.get("source", {}).get("url") or "").strip()
        offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        price_value = item.get("price_num", offer.get("price"))
        currency = item.get("currency") or offer.get("currency")
        availability = item.get("availability") or offer.get("availability") or "unknown"
        sku = item.get("sku")
        identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
        sku_data = identity.get("sku") if isinstance(identity.get("sku"), dict) else {}
        external_id = str(sku or sku_data.get("value") or url).strip()
        if not title or not brand or not url or not external_id:
            return None
        try:
            normalized = normalize_product(
                brand, title,
                concentration=item.get("concentration"),
                size_ml=item.get("size_ml"),
            )
            price = Decimal(str(price_value)) if price_value is not None else None
        except (ValueError, InvalidOperation, TypeError):
            return None
        record = OfferRecord(
            store="deloox", external_product_id=external_id,
            brand=brand, fragrance=normalized.fragrance_name,
            concentration=normalized.concentration, size_ml=normalized.size_ml,
            gtin=item.get("gtin"), title=title, url=url, price=price,
            currency=currency, availability=availability,
            captured_at=datetime.now(timezone.utc).isoformat(),
            source="jsonld_or_html", external_offer_id=external_id,
        )
        return record

    def parse_raw(self, raw: Any) -> Sequence[OfferRecord]:
        """Parse a saved HTML fixture tuple (url, html, query) without network."""
        if isinstance(raw, dict):
            rows = [raw]
        elif isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], dict):
            rows = list(raw)
        elif isinstance(raw, tuple) and len(raw) == 3:
            url, html, query = raw
            parsed = scraper.extract_product_page(None, url, query=query, html=html)
            rows = [parsed] if parsed else []
        else:
            raise ValueError("deloox_parse_raw_requires_product_mapping_or_(url,html,query)")
        return tuple(record for row in rows if (record := self._map_product(row)) is not None)

    def validate_offer(self, offer: OfferRecord) -> tuple[bool, tuple[str, ...]]:
        return validate_offer(offer)

    async def discover_products(self) -> Sequence[dict]:
        if not self.discovery_terms:
            return ()
        found: dict[str, OfferRecord] = {}
        for term in self.discovery_terms:
            await self._limiter.acquire()
            rows = await asyncio.to_thread(self._search, term)
            self._raw_artifacts.append({"format": "json", "data": rows, "metadata": {"query": term}})
            for record in self.parse_raw(rows or []):
                found[record.external_product_id] = record
        self._offers.update(found)
        return tuple({"externalProductId": x.external_product_id, "title": x.title,
                      "url": x.url, "store": self.store_key} for x in found.values())

    async def fetch_product(self, external_id: str) -> dict | None:
        key = str(external_id)
        if key in self._offers:
            return self._offers[key].to_dict()
        if self._page_loader is None:
            return None
        await self._limiter.acquire()
        loaded = await asyncio.to_thread(self._page_loader, key)
        capture_raw_page_artifact(self._raw_artifacts, loaded, requested_url=key, store_key=self.store_key)
        record = self.parse_raw(loaded)
        if not record:
            return None
        self._offers[record[0].external_product_id] = record[0]
        return record[0].to_dict()

    async def fetch_offers(self, product_key: str) -> Sequence[OfferRecord]:
        if not self._offers and self.discovery_terms:
            await self.discover_products()
        key = str(product_key)
        return tuple(x for x in self._offers.values()
                     if x.external_product_id == key or x.url == key)

    async def fetch_price_and_stock(self, offer_id: str) -> OfferRecord | None:
        product = await self.fetch_product(offer_id)
        if product is None:
            return None
        return self._offers.get(str(offer_id)) or next(
            (x for x in self._offers.values() if x.url == str(offer_id)), None
        )

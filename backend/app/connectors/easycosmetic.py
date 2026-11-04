"""Easycosmetic adapter using its existing regional product-page parser.

The parser preserves the German storefront's selected-variant price and stock
signals. This adapter maps that evidence to the shared contract and does not
write to the catalog.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence

from app.connectors.base import OfferRecord, RateLimiter, validate_offer
from app.services.product_normalization import normalize_product
from scrapers.easycosmetic import scraper


class EasycosmeticConnector:
    store_key = "easycosmetic"
    source_kind = "product_page_jsonld_html"

    def __init__(self, discovery_terms: Sequence[str] = (), *, search_func: Callable | None = None,
                 page_loader: Callable[[str], Any] | None = None):
        self.discovery_terms = tuple(x.strip() for x in discovery_terms if x and x.strip())
        self._search = search_func or scraper.search
        self._page_loader = page_loader
        self._limiter = RateLimiter(0.5)
        self._offers: dict[str, OfferRecord] = {}

    @staticmethod
    def _map_product(item: dict[str, Any]) -> OfferRecord | None:
        if not isinstance(item, dict):
            return None
        title = str(item.get("name") or "").strip()
        brand = str(item.get("brand") or "").strip()
        url = str(item.get("url") or "").strip()
        price_value = item.get("price_num")
        currency = item.get("currency") or "EUR"
        raw_stock = str(item.get("availability") or "").strip().casefold()
        if item.get("available") is True or raw_stock in {"in stock", "available"}:
            availability = "in_stock"
        elif item.get("available") is False or raw_stock in {"out of stock", "sold out"}:
            availability = "out_of_stock"
        elif "preorder" in raw_stock or "pre order" in raw_stock:
            availability = "preorder"
        else:
            availability = "unknown"
        external_id = str(item.get("sku") or item.get("gtin") or url).strip()
        if not title or not brand or not url or not external_id:
            return None
        try:
            identity = normalize_product(brand, title, size_ml=item.get("size_ml"))
            price = Decimal(str(price_value)) if price_value is not None else None
        except (ValueError, InvalidOperation, TypeError):
            return None
        return OfferRecord(
            store="easycosmetic", external_product_id=external_id,
            brand=brand, fragrance=identity.fragrance_name,
            concentration=identity.concentration, size_ml=identity.size_ml,
            gtin=item.get("gtin"), title=title, url=url, price=price,
            currency=currency, availability=availability,
            captured_at=datetime.now(timezone.utc).isoformat(),
            source="product_page_jsonld_html", external_offer_id=external_id,
        )

    def parse_raw(self, raw: Any) -> Sequence[OfferRecord]:
        """Parse saved HTML as (product URL, HTML); never performs a request."""
        if isinstance(raw, dict):
            rows = [raw]
        elif isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], dict):
            rows = list(raw)
        elif isinstance(raw, tuple) and len(raw) == 2:
            url, html = raw
            parsed = scraper.extract_product_page(None, url, html=html)
            rows = [parsed] if parsed else []
        else:
            raise ValueError("easycosmetic_parse_raw_requires_mapping_or_(url,html)")
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
        records = self.parse_raw(loaded)
        if not records:
            return None
        self._offers[records[0].external_product_id] = records[0]
        return records[0].to_dict()

    async def fetch_offers(self, product_key: str) -> Sequence[OfferRecord]:
        if not self._offers and self.discovery_terms:
            await self.discover_products()
        key = str(product_key)
        return tuple(x for x in self._offers.values()
                     if x.external_product_id == key or x.url == key)

    async def fetch_price_and_stock(self, offer_id: str) -> OfferRecord | None:
        await self.fetch_product(offer_id)
        return self._offers.get(str(offer_id)) or next(
            (x for x in self._offers.values() if x.url == str(offer_id)), None
        )

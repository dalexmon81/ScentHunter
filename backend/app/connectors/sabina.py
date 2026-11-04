"""Sabina adapter over the existing product-page parser.

The retailer scraper owns page interpretation; this adapter only converts its
saved HTML or structured result into the shared offer contract. No catalog
writes are performed here.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence

from app.connectors.base import OfferRecord, RateLimiter, validate_offer
from app.services.product_normalization import normalize_product
from scrapers.sabina import scraper


class SabinaConnector:
    store_key = "sabina"
    source_kind = "product_page_jsonld_html"

    def __init__(self, discovery_terms: Sequence[str] = (), *,
                 search_func: Callable | None = None,
                 page_loader: Callable[[str], Any] | None = None):
        self.discovery_terms = tuple(x.strip() for x in discovery_terms if x and x.strip())
        self._search = search_func or scraper.search
        self._page_loader = page_loader
        self._limiter = RateLimiter(0.5)
        self._offers: dict[str, OfferRecord] = {}

    @staticmethod
    def _value(container: Any, key: str) -> Any:
        value = container.get(key) if isinstance(container, dict) else None
        return value.get("value") if isinstance(value, dict) else value

    @classmethod
    def _map_product(cls, item: dict[str, Any]) -> tuple[OfferRecord, ...]:
        if not isinstance(item, dict):
            return ()
        # Discovery/test adapters may supply a flat scraper-compatible row.
        # Convert it to the same evidence shape emitted by the legacy parser.
        if not isinstance(item.get("source"), dict):
            item = {
                **item,
                "source": {
                    "url": item.get("url"), "name": item.get("name"),
                    "brand": item.get("brand"),
                },
                "identity": {
                    "store_product_id": item.get("product_id"),
                    "sku": item.get("sku"), "gtin": item.get("gtin"),
                },
                "attributes": {
                    "size_ml": item.get("size_ml"),
                    "concentration": item.get("concentration"),
                },
                "offer": {
                    "price": item.get("price_num", item.get("price")),
                    "currency": item.get("currency"),
                    "availability": item.get("availability", "unknown"),
                },
            }
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
        attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        title = str(item.get("name") or source.get("name") or "").strip()
        brand = str(item.get("brand") or source.get("brand") or "").strip()
        url = str(item.get("url") or source.get("url") or "").strip()
        product_id = cls._value(identity, "store_product_id")
        gtin = cls._value(identity, "gtin")
        if not title or not brand or not url:
            return ()
        captured_at = datetime.now(timezone.utc).isoformat()
        rows: list[OfferRecord] = []
        seen_records: set[tuple[str, str, str]] = set()

        def add(*, external_id: Any, row_title: str, row_url: str,
                raw_price: Any, currency: Any, availability: Any,
                size_ml: Any, row_gtin: Any = None) -> None:
            if raw_price in (None, ""):
                return
            try:
                price = Decimal(str(raw_price))
                normalized = normalize_product(
                    brand, row_title,
                    concentration=cls._value(attributes, "concentration"),
                    size_ml=size_ml,
                )
            except (ValueError, InvalidOperation, TypeError):
                return
            identifier = str(external_id or row_url).strip()
            if not identifier:
                return
            signature = (str(normalized.size_ml), str(price), str(normalized.concentration))
            if signature in seen_records:
                return
            seen_records.add(signature)
            stock = str(availability or "unknown").strip().casefold()
            if stock not in {"in_stock", "out_of_stock", "preorder", "unknown"}:
                stock = "unknown"
            rows.append(OfferRecord(
                store=cls.store_key, external_product_id=identifier,
                brand=brand, fragrance=normalized.fragrance_name,
                concentration=normalized.concentration, size_ml=normalized.size_ml,
                gtin=str(row_gtin or gtin or "").strip() or None,
                title=row_title, url=row_url, price=price,
                currency=str(currency or "EUR").upper(), availability=stock,
                captured_at=captured_at, source=cls.source_kind,
                external_offer_id=identifier,
            ))

        size = cls._value(attributes, "size_ml")
        add(
            external_id=cls._value(identity, "sku") or product_id or url,
            row_title=title, row_url=url, raw_price=offer.get("price"),
            currency=offer.get("currency"), availability=offer.get("availability"),
            size_ml=size, row_gtin=gtin,
        )
        for index, variant in enumerate(item.get("variants") or []):
            if not isinstance(variant, dict):
                continue
            variant_url = str(variant.get("url") or url).strip()
            variant_size = variant.get("size_ml")
            variant_id = variant.get("sku") or variant.get("gtin") or (
                f"{product_id or url}#variant-{index}"
            )
            add(
                external_id=variant_id, row_title=title, row_url=variant_url,
                raw_price=variant.get("price_num"), currency=variant.get("currency"),
                availability=variant.get("availability"), size_ml=variant_size,
                row_gtin=variant.get("gtin"),
            )
        return tuple(rows)

    def parse_raw(self, raw: Any) -> Sequence[OfferRecord]:
        """Parse a saved (product URL, HTML) tuple or scraper result mapping."""
        if isinstance(raw, dict):
            rows = [raw]
        elif isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], dict):
            rows = list(raw)
        elif isinstance(raw, tuple) and len(raw) in (2, 3):
            url, html = raw[0], raw[1]
            query = raw[2] if len(raw) == 3 else ""
            parsed = scraper.extract_product_page(
                None, url, query=query, html=html
            )
            rows = [parsed] if parsed else []
        else:
            raise ValueError("sabina_parse_raw_requires_mapping_or_(url,html[,query])")
        return tuple(record for row in rows for record in self._map_product(row))

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
        return tuple({
            "externalProductId": x.external_product_id,
            "title": x.title, "url": x.url, "store": self.store_key,
        } for x in found.values())

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
        for record in records:
            self._offers[record.external_product_id] = record
        match = self._offers.get(key) or records[0]
        return match.to_dict()

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

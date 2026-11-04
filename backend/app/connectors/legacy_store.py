"""Shared bridge from legacy retailer scrapers to the universal offer contract."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence
from urllib.parse import urlparse

import requests
from app.connectors.base import OfferRecord, RateLimiter, validate_offer
from app.services.product_normalization import normalize_product


def _value(value):
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _first(*values):
    for value in values:
        value = _value(value)
        if value not in (None, ""):
            return value
    return None


def _availability(value):
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    text = str(value or "").lower().replace("_", "").replace("-", "").replace(" ", "")
    if any(x in text for x in ("outofstock", "soldout", "unavailable", "ausverkauft")):
        return "out_of_stock"
    if any(x in text for x in ("instock", "available", "auf lager")):
        return "in_stock"
    if "preorder" in text:
        return "preorder"
    return "unknown"


class LegacyStoreConnector:
    """Universal adapter around an existing store-specific discovery/parser pair."""
    def __init__(self, store_key: str, scraper: Any, *,
                 page_parser: Callable | None = None,
                 discovery_terms: Sequence[str] = (),
                 search_func: Callable | None = None,
                 page_loader: Callable[[str, str], Any] | None = None):
        self.store_key = store_key
        self.source_kind = "legacy_store_parser"
        self.scraper = scraper
        self.page_parser = page_parser
        self.discovery_terms = tuple(str(x).strip() for x in discovery_terms if str(x).strip())
        self._search = search_func or scraper.search
        self._page_loader = page_loader
        self._limiter = RateLimiter(0.5)
        self._offers: dict[str, OfferRecord] = {}
        self._raw_artifacts: list[dict[str, Any]] = []
        self._raw_by_external_id: dict[str, Any] = {}

    def _map(self, item: Any) -> tuple[OfferRecord, ...]:
        if not isinstance(item, dict):
            return ()
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        identity = item.get("identity") if isinstance(item.get("identity"), dict) else {}
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
        title = str(_first(item.get("name"), source.get("source_name"), source.get("name")) or "").strip()
        brand = str(_first(item.get("brand"), source.get("source_brand"), source.get("brand")) or "").strip()
        url = str(_first(item.get("url"), source.get("url")) or "").strip()
        if not title or not brand or not url:
            return ()
        raw_price = _first(item.get("price_num"), offer.get("price"), item.get("price"))
        try:
            price = Decimal(str(raw_price)) if raw_price is not None else None
        except (InvalidOperation, TypeError, ValueError):
            return ()
        raw_size = _first(item.get("size_ml"), attrs.get("size_ml"))
        raw_conc = _first(item.get("concentration"), attrs.get("concentration"))
        try:
            normalized = normalize_product(brand, title, concentration=raw_conc, size_ml=raw_size)
        except (ValueError, TypeError):
            return ()
        external = _first(
            identity.get("store_variant_id"), identity.get("sku"),
            identity.get("store_product_id"), identity.get("gtin"),
            item.get("sku"), item.get("gtin"), item.get("product_id"),
        )
        external_id = str(external or url).strip()
        currency = str(_first(item.get("currency"), offer.get("currency")) or "EUR").upper()
        stock = _availability(_first(item.get("availability"), offer.get("availability"), item.get("available")))
        gtin = _first(identity.get("gtin"), item.get("gtin"))
        captured = datetime.now(timezone.utc).isoformat()
        return (OfferRecord(
            store=self.store_key, external_product_id=external_id, brand=brand,
            fragrance=normalized.fragrance_name, concentration=normalized.concentration,
            size_ml=normalized.size_ml, gtin=str(gtin) if gtin else None,
            title=title, url=url, price=price, currency=currency,
            availability=stock, captured_at=captured, source=self.source_kind,
            external_offer_id=external_id,
        ),)

    def parse_raw(self, raw: Any) -> Sequence[OfferRecord]:
        if isinstance(raw, dict):
            rows = [raw]
        elif isinstance(raw, (list, tuple)):
            rows = [x for x in raw if isinstance(x, dict)]
        else:
            raise ValueError(f"{self.store_key}_parse_raw_requires_product_mapping")
        records = []
        for row in rows:
            mapped = self._map(row)
            records.extend(mapped)
            for record in mapped:
                self._raw_by_external_id[record.external_product_id] = row
        return tuple(records)

    def raw_evidence_for(self, external_id: str):
        """Return the original structured retailer row used to build an offer."""
        return self._raw_by_external_id.get(str(external_id))

    def validate_offer(self, offer: OfferRecord):
        return validate_offer(offer)

    async def _load_page(self, url: str, query: str):
        if self._page_loader is not None:
            result = self._page_loader(url, query)
            if hasattr(result, "__await__"):
                result = await result
            self._raw_artifacts.append({"format": "html" if isinstance(result, (str, bytes)) else "json", "data": result, "source_url": url})
            return result
        if self.page_parser is None:
            return None
        def load():
            with requests.Session() as session:
                return self.page_parser(session, url, query)
        return await asyncio.to_thread(load)

    async def discover_products(self):
        if not self.discovery_terms:
            return ()
        found: dict[str, OfferRecord] = {}
        for term in self.discovery_terms:
            await self._limiter.acquire()
            rows = await asyncio.to_thread(self._search, term)
            self._raw_artifacts.append({"format": "json", "data": rows, "metadata": {"query": term}})
            for record in self.parse_raw(rows or []):
                found[record.external_product_id] = record
            # Some legacy search endpoints return candidate URLs only. Enrich
            # those candidates through the retailer's authoritative page parser.
            for row in (rows or []):
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if not url or any(x.url == url for x in found.values()):
                    continue
                if self.page_parser is None and self._page_loader is None:
                    continue
                await self._limiter.acquire()
                detail = await self._load_page(url, term)
                for record in self.parse_raw(detail or []):
                    found[record.external_product_id] = record
        self._offers.update(found)
        return tuple({"externalProductId": x.external_product_id, "title": x.title,
                      "url": x.url, "store": self.store_key} for x in found.values())

    async def fetch_product(self, external_id: str):
        key = str(external_id)
        if key in self._offers:
            return self._offers[key].to_dict()
        if self.page_parser is None and self._page_loader is None:
            return None
        await self._limiter.acquire()
        loaded = await self._load_page(key, key.rsplit("/", 1)[-1])
        records = self.parse_raw(loaded or [])
        for record in records:
            self._offers[record.external_product_id] = record
        match = self._offers.get(key) or next((x for x in records if x.url == key), None)
        return match.to_dict() if match else None

    async def fetch_offers(self, product_key: str):
        if not self._offers and self.discovery_terms:
            await self.discover_products()
        key = str(product_key)
        return tuple(x for x in self._offers.values()
                     if x.external_product_id == key or x.url == key)

    async def fetch_price_and_stock(self, offer_id: str):
        await self.fetch_product(offer_id)
        return self._offers.get(str(offer_id)) or next(
            (x for x in self._offers.values() if x.url == str(offer_id)), None)

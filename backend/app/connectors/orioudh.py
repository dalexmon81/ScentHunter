"""Variant-aware Orioudh Shopify connector for background ingestion."""
from __future__ import annotations
import asyncio, os, time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse
import requests
from app.connectors.base import ConnectorUnavailable, DiscoveredProduct, StoreConnector

class OrioudhConnector(StoreConnector):
    store_key = "orioudh"
    def __init__(self, scraper_module: Any | None = None) -> None:
        super().__init__()
        if scraper_module is None:
            from scrapers.orioudh import scraper as scraper_module
        self._scraper = scraper_module
        self._snapshot: tuple[str, ...] = ()
        self._cached_at = 0.0

    def _queries(self) -> tuple[str, ...]:
        values = tuple(dict.fromkeys(x.strip() for x in os.environ.get("SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH", "").split(";") if x.strip()))
        if not values: raise ValueError("SCENTHUNTER_DISCOVERY_QUERIES_ORIOUDH must contain operator-approved queries")
        return values

    def _discover_sync(self) -> tuple[str, ...]:
        urls, seen, verified = [], set(), False
        for query in self._queries():
            report = self._scraper.search_stream(query)
            if not isinstance(report, Mapping) or report.get("status") in {"timeout","unavailable","blocked","error"}:
                raise ConnectorUnavailable("Orioudh discovery failed")
            verified = verified or report.get("verified") is True
            for row in report.get("results") or ():
                url = str(row.get("url") or "").strip() if isinstance(row, Mapping) else ""
                p = urlparse(url)
                if p.scheme in {"http","https"} and p.netloc and "/products/" in p.path and url not in seen:
                    seen.add(url); urls.append(url)
        if not verified: raise ConnectorUnavailable("Orioudh discovery was not verified")
        return tuple(urls)

    async def discover_products(self, *, cursor: str | None = None, limit: int = 100) -> Sequence[DiscoveredProduct]:
        if isinstance(limit,bool) or not 1 <= limit <= 1000: raise ValueError("limit must be between 1 and 1000")
        try: offset=int(cursor or "0")
        except (TypeError,ValueError): raise ValueError("cursor must be a non-negative integer") from None
        if offset < 0: raise ValueError("cursor must be a non-negative integer")
        if not self._snapshot or time.monotonic()-self._cached_at >= 900:
            self._snapshot=await asyncio.to_thread(self._discover_sync); self._cached_at=time.monotonic()
        return tuple(DiscoveredProduct(url,url,{"discovery_source":"orioudh_scraper"}) for url in self._snapshot[offset:offset+limit])

    def _fetch_sync(self,url:str):
        p=urlparse(url)
        if p.scheme not in {"http","https"} or not p.netloc or "/products/" not in p.path: raise ValueError("external_product_id must be an absolute Shopify product URL")
        s=requests.Session()
        try:
            rows=self._scraper.extract_product_page(s,url,"")
            if not isinstance(rows,list): raise ConnectorUnavailable("Orioudh parser returned a non-list variant payload")
            return {"url":url,"variants":rows}
        except requests.RequestException as exc: raise ConnectorUnavailable(f"Orioudh fetch failed: {type(exc).__name__}") from exc
        finally: s.close()

    async def fetch_product(self, external_product_id:str) -> Mapping[str,Any] | None:
        return await asyncio.to_thread(self._fetch_sync,str(external_product_id or "").strip())

    def _variant_id(self,row:Mapping[str,Any]) -> str:
        ident=row.get("identity") if isinstance(row.get("identity"),Mapping) else {}
        v=ident.get("store_variant_id") if isinstance(ident.get("store_variant_id"),Mapping) else {}
        product=ident.get("store_product_id") if isinstance(ident.get("store_product_id"),Mapping) else {}
        if v.get("value") is None or product.get("value") is None: raise ValueError("Orioudh variant is missing stable Shopify product/variant IDs")
        return f"{product['value']}:{v['value']}"

    async def fetch_offers(self, product_key:str) -> Sequence[Mapping[str,Any]]:
        raw=await self.fetch_product(product_key)
        if not isinstance(raw,Mapping): return ()
        return tuple({**dict(row),"url":product_key,"external_product_id":self._variant_id(row)} for row in raw.get("variants",()) if isinstance(row,Mapping))

    async def fetch_offer_price_and_stock(self, offer_id: str, product_url: str | None = None) -> Mapping[str, Any]:
        return await self.fetch_price_and_stock(offer_id, product_url=product_url)

    async def fetch_price_and_stock(self, offer_id:str, product_url:str|None=None) -> Mapping[str,Any]:
        if ":" not in offer_id: raise ValueError("offer_id must contain Shopify product ID and variant ID")
        product_id,variant_id=offer_id.split(":",1)
        # The persisted Offer URL is authoritative. Do not depend on a process-local
        # discovery snapshot: workers can restart between ingestion and refresh.
        urls=(product_url,) if product_url else self._snapshot
        match=None
        for url in urls:
            raw=await self.fetch_product(url)
            if not isinstance(raw,Mapping): continue
            for row in raw.get("variants",()):
                if isinstance(row,Mapping) and self._variant_id(row)==offer_id: match={**dict(row),"url":url,"external_product_id":offer_id}; break
            if match: break
        if not match: raise LookupError("orioudh_variant_not_found")
        return {**self.parse_raw(match),"captured_at":time.time(),"raw_record":match}

    def parse_raw(self,raw:Mapping[str,Any])->Mapping[str,Any]:
        src=raw.get("source") if isinstance(raw.get("source"),Mapping) else {}
        ident=raw.get("identity") if isinstance(raw.get("identity"),Mapping) else {}
        attrs=raw.get("attributes") if isinstance(raw.get("attributes"),Mapping) else {}
        offer=raw.get("offer") if isinstance(raw.get("offer"),Mapping) else {}
        def val(x): return x.get("value") if isinstance(x,Mapping) else x
        url=str(raw.get("url") or src.get("url") or "")
        currency=str(offer.get("currency") or "EUR").upper()
        return {"external_product_id":raw.get("external_product_id") or self._variant_id(raw),"raw_name":raw.get("name") or src.get("source_name"),"brand_raw":src.get("source_brand"),"size_ml":val(attrs.get("size_ml")),"concentration":val(attrs.get("concentration")),"gtin":val(ident.get("gtin")),"sku":val(ident.get("sku")),"price":str(offer.get("price")) if offer.get("price") is not None else None,"currency":currency,"currency_explicit":offer.get("currency_explicit") is True and bool(offer.get("currency")),"currency_source":offer.get("currency_source") if offer.get("currency_explicit") is True else None,"availability":offer.get("availability"),"product_url":url,"url":url,"image_url":src.get("image"),"source":"orioudh_scraper","raw_payload":dict(raw)}
def build_orioudh_connector(): return OrioudhConnector()

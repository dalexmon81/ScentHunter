"""Variant-aware ParfumCity Shopify connector for background ingestion."""
from __future__ import annotations
import asyncio, os, time
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse
import requests
from app.connectors.base import ConnectorUnavailable, DiscoveredProduct, StoreConnector

class ParfumCityConnector(StoreConnector):
    store_key="parfumcity"
    def __init__(self,scraper_module:Any|None=None):
        super().__init__()
        if scraper_module is None:
            from scrapers.parfumcity import scraper as scraper_module
        self._scraper=scraper_module; self._snapshot=(); self._cached_at=0.0
    @staticmethod
    def _is_store_product_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"parfumcity.nl", "www.parfumcity.nl"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 80, 443)
            and "/products/" in parsed.path.lower()
        )

    def _queries(self):
        q=tuple(dict.fromkeys(x.strip() for x in os.environ.get("SCENTHUNTER_DISCOVERY_QUERIES_PARFUMCITY","").split(";") if x.strip()))
        if not q: raise ValueError("SCENTHUNTER_DISCOVERY_QUERIES_PARFUMCITY must contain operator-approved queries")
        return q
    def _discover_sync(self):
        s=requests.Session(); s.max_redirects = 0; urls=[]; seen=set(); verified=False
        try:
            for query in self._queries():
                rows,errors,ok=self._scraper.discover(s,query); verified=verified or bool(ok)
                for url in rows or ():
                    if self._is_store_product_url(url) and url not in seen:
                        seen.add(url); urls.append(url)
            if not verified: raise ConnectorUnavailable("ParfumCity discovery was not verified")
            return tuple(urls)
        except requests.RequestException as exc: raise ConnectorUnavailable(f"ParfumCity discovery failed: {type(exc).__name__}") from exc
        finally: s.close()
    async def discover_products(self,*,cursor:str|None=None,limit:int=100)->Sequence[DiscoveredProduct]:
        if isinstance(limit,bool) or not 1<=limit<=1000: raise ValueError("limit must be between 1 and 1000")
        try: offset=int(cursor or "0")
        except (TypeError,ValueError): raise ValueError("cursor must be a non-negative integer") from None
        if offset<0: raise ValueError("cursor must be a non-negative integer")
        if not self._snapshot or time.monotonic()-self._cached_at>=900:
            self._snapshot=await asyncio.to_thread(self._discover_sync); self._cached_at=time.monotonic()
        return tuple(DiscoveredProduct(u,u,{"discovery_source":"parfumcity_scraper"}) for u in self._snapshot[offset:offset+limit])
    def _fetch_sync(self,url):
        if not self._is_store_product_url(url): raise ValueError("external_product_id must be a ParfumCity Shopify product URL")
        s=requests.Session()
        try:
            product=self._scraper.product_json(s,url)
            if not isinstance(product,Mapping): return None
            return {"product":dict(product),"url":url}
        except requests.RequestException as exc: raise ConnectorUnavailable(f"ParfumCity fetch failed: {type(exc).__name__}") from exc
        finally: s.close()
    async def fetch_product(self,external_product_id:str)->Mapping[str,Any]|None:
        return await asyncio.to_thread(self._fetch_sync,str(external_product_id or "").strip())
    def _item(self,product,url,variant):
        item=self._scraper.make_item(product,variant,url,str(product.get("title") or ""))
        if not isinstance(item,Mapping): return None
        ident=item.get("identity") if isinstance(item.get("identity"),Mapping) else {}
        pid=ident.get("store_product_id") if isinstance(ident.get("store_product_id"),Mapping) else {}
        vid=ident.get("store_variant_id") if isinstance(ident.get("store_variant_id"),Mapping) else {}
        if pid.get("value") is None or vid.get("value") is None: return None
        return {**dict(item),"external_product_id":f"{pid['value']}:{vid['value']}","url":url}
    async def fetch_offers(self,product_key:str)->Sequence[Mapping[str,Any]]:
        raw=await self.fetch_product(product_key)
        if not isinstance(raw,Mapping): return ()
        product=raw["product"]
        return tuple(item for v in product.get("variants",()) if isinstance(v,Mapping) and (item:=self._item(product,product_key,v)) is not None)
    async def fetch_offer_price_and_stock(self, offer_id: str, product_url: str | None = None) -> Mapping[str, Any]:
        return await self.fetch_price_and_stock(offer_id, product_url=product_url)

    async def fetch_price_and_stock(self,offer_id:str,product_url:str|None=None)->Mapping[str,Any]:
        if ":" not in offer_id: raise ValueError("offer_id must contain Shopify product ID and variant ID")
        # Prefer the URL persisted with the Offer row. A restarted worker has no
        # discovery snapshot, so refresh must not rely on process-local cache.
        urls=(product_url,) if product_url else self._snapshot
        for url in urls:
            raw=await self.fetch_product(url)
            if not isinstance(raw,Mapping): continue
            product=raw["product"]
            for v in product.get("variants",()):
                if not isinstance(v,Mapping): continue
                item=self._item(product,url,v)
                if item and item["external_product_id"]==offer_id:
                    return {**self.parse_raw(item),"captured_at":time.time(),"raw_record":item}
        raise LookupError("parfumcity_variant_not_found")
    def parse_raw(self,raw:Mapping[str,Any])->Mapping[str,Any]:
        src=raw.get("source") if isinstance(raw.get("source"),Mapping) else {}
        ident=raw.get("identity") if isinstance(raw.get("identity"),Mapping) else {}
        attrs=raw.get("attributes") if isinstance(raw.get("attributes"),Mapping) else {}
        offer=raw.get("offer") if isinstance(raw.get("offer"),Mapping) else {}
        def val(x): return x.get("value") if isinstance(x,Mapping) else x
        url=str(raw.get("url") or src.get("url") or "")
        return {"external_product_id":raw.get("external_product_id"),"raw_name":raw.get("name") or src.get("source_name"),"brand_raw":src.get("source_brand"),"size_ml":val(attrs.get("size_ml")),"concentration":val(attrs.get("concentration")),"gtin":val(ident.get("gtin")),"sku":val(ident.get("sku")),"price":str(offer.get("price")) if offer.get("price") is not None else None,"currency":str(offer.get("currency") or "EUR").upper(),"currency_explicit":offer.get("currency_explicit") is True and bool(offer.get("currency")),"currency_source":offer.get("currency_source") if offer.get("currency_explicit") is True else None,"availability":offer.get("availability"),"product_url":url,"url":url,"image_url":src.get("image"),"source":"parfumcity_scraper","raw_payload":dict(raw)}
def build_parfumcity_connector(): return ParfumCityConnector()

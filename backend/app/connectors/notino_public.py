"""Direct Notino.fr storefront connector for the PostgreSQL catalog worker.

Discovery uses bounded public storefront search; fetch and refresh independently
read the discovered product page. This connector has no CJ/VIV dependency.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from app.connectors.base import ConnectorUnavailable, DiscoveredProduct, StoreConnector
from scrapers.notino import scraper


class NotinoPublicStorefrontConnector(StoreConnector):
    store_key = "notino"
    DEFAULT_QUERIES = (
        "French Avenue Liquid Brun Eau de Parfum",
        "Dior Sauvage Eau de Parfum",
        "Bleu de Chanel Eau de Parfum",
        "Yves Saint Laurent Y Eau de Parfum",
        "Acqua di Gio Profondo Eau de Parfum",
    )

    def __init__(self) -> None:
        super().__init__()
        self._candidates: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _brand_from_url_title(url: str, name: str) -> str:
        """Use a URL brand slug only when the product title repeats that prefix."""
        try:
            segment = urlparse(url).path.strip("/").split("/", 1)[0]
        except ValueError:
            return ""
        slug_words = [word for word in re.split(r"[-_]+", segment) if word]
        if not slug_words or not name:
            return ""
        slug_prefix = " ".join(slug_words)
        if not scraper._norm(name).startswith(scraper._norm(slug_prefix) + " "):
            return ""
        title_words = str(name).split()
        return " ".join(title_words[:len(slug_words)])

    def _queries(self) -> tuple[str, ...]:
        raw = os.environ.get("SCENTHUNTER_DISCOVERY_QUERIES_NOTINO", "")
        values = tuple(dict.fromkeys(item.strip() for item in raw.split(";") if item.strip()))
        return values or self.DEFAULT_QUERIES

    @staticmethod
    def _discover_query(query: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        previous_limits = (scraper.TIMEOUT, scraper.READER_TIMEOUT, scraper.RETRY_COUNT)
        scraper.TIMEOUT, scraper.READER_TIMEOUT, scraper.RETRY_COUNT = 4, 6, 0
        session = scraper._new_session()
        try:
            return scraper._discover(query, session, query_limit=1, allow_sitemap=False)
        except Exception as exc:
            raise ConnectorUnavailable(
                f"Notino public discovery failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            session.close()
            scraper.TIMEOUT, scraper.READER_TIMEOUT, scraper.RETRY_COUNT = previous_limits

    async def discover_products(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> Sequence[DiscoveredProduct]:
        if isinstance(limit, bool) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            offset = int(cursor or "0")
        except (TypeError, ValueError):
            raise ValueError("cursor must be a non-negative integer") from None
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer")

        candidates: dict[str, dict[str, Any]] = {}
        for query in self._queries():
            rows, _diagnostics = await asyncio.to_thread(self._discover_query, query)
            for candidate in rows:
                url = scraper._allowed_url(str(candidate.get("url") or ""), scraper.BASE_URL)
                if not url:
                    continue
                row = dict(candidate)
                name = str(row.get("name") or "").strip()
                if scraper._has_non_perfume_marker(name):
                    continue
                if not row.get("brand"):
                    brand = self._brand_from_url_title(url, name)
                    if brand:
                        row["brand"] = brand
                row["query"] = query
                candidates.setdefault(url, row)

        ordered = list(candidates.values())
        page = ordered[offset:offset + limit]
        discovered: list[DiscoveredProduct] = []
        for candidate in page:
            url = str(candidate["url"])
            self._candidates[url] = candidate
            discovered.append(DiscoveredProduct(
                external_product_id=url,
                product_url=url,
                raw_payload={"query": candidate.get("query"), "name": candidate.get("name")},
            ))
        return tuple(discovered)

    def _fetch_sync(self, url: str, candidate: Mapping[str, Any]) -> Mapping[str, Any] | None:
        safe_url = scraper._allowed_url(url, scraper.BASE_URL)
        if not safe_url or safe_url.rstrip("/") != url.rstrip("/"):
            raise ValueError("Notino external_product_id must be a safe HTTPS Notino.fr product URL")
        parsed = urlparse(safe_url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.notino.fr", "notino.fr"}:
            raise ValueError("Notino external_product_id must be an HTTPS Notino.fr product URL")
        query = str(candidate.get("query") or candidate.get("name") or scraper._slug_name(url)).strip()
        if not query:
            query = scraper._slug_name(url)
        request_candidate = dict(candidate)
        request_candidate.update({"url": url, "name": candidate.get("name") or scraper._slug_name(url),
                                  "source": "known-product-url"})
        previous_limits = (scraper.TIMEOUT, scraper.READER_TIMEOUT, scraper.RETRY_COUNT)
        scraper.TIMEOUT, scraper.READER_TIMEOUT, scraper.RETRY_COUNT = 4, 6, 0
        session = scraper._new_session()
        try:
            result = scraper._reader_product(session, request_candidate, query, _allow_variants=False)
        except Exception as exc:
            raise ConnectorUnavailable(
                f"Notino public product fetch failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            session.close()
            scraper.TIMEOUT, scraper.READER_TIMEOUT, scraper.RETRY_COUNT = previous_limits

        if isinstance(result, list):
            matching = [
                row for row in result if isinstance(row, Mapping)
                and scraper.normaliseurl(str(row.get("url") or "")).rstrip("/") == url.rstrip("/")
            ]
            result = matching[0] if matching else None
        if not isinstance(result, Mapping):
            return None
        result_url = scraper._allowed_url(str(result.get("url") or ""), scraper.BASE_URL)
        if not result_url or result_url.rstrip("/") != url.rstrip("/"):
            return None

        captured_at = datetime.now(timezone.utc).isoformat()
        price = scraper._price(result.get("price"))
        if price is None:
            return None
        availability = str(result.get("availability") or "").strip().lower()
        if availability in {"in stock", "instock", "available"}:
            availability = "in_stock"
        elif availability in {"out of stock", "outofstock", "unavailable"}:
            availability = "out_of_stock"
        else:
            availability = "unknown"

        return {
            **dict(result),
            "external_product_id": url,
            "product_url": url,
            "url": url,
            "price": f"{price:.2f}",
            "currency": "EUR",
            "currency_explicit": result.get("currency_explicit") is True,
            "availability": availability,
            "captured_at": captured_at,
            "source": "notino_public_storefront",
        }

    async def fetch_product(self, external_product_id: str) -> Mapping[str, Any] | None:
        url = str(external_product_id or "").strip()
        if not url:
            raise ValueError("external_product_id is required")
        candidate = self._candidates.get(url) or {
            "url": url,
            "name": scraper._slug_name(url),
            "query": scraper._slug_name(url),
            "source": "known-product-url",
        }
        return await asyncio.to_thread(self._fetch_sync, url, candidate)

    async def fetch_offers(self, product_key: str) -> Sequence[Mapping[str, Any]]:
        row = await self.fetch_product(product_key)
        return (row,) if isinstance(row, Mapping) else ()

    async def fetch_price_and_stock(self, offer_id: str) -> Mapping[str, Any]:
        row = await self.fetch_product(offer_id)
        if not isinstance(row, Mapping):
            raise LookupError("notino_public_product_not_found_or_unverified")
        return {
            "external_product_id": row["external_product_id"],
            "product_url": row["product_url"],
            "url": row["url"],
            "price": row["price"],
            "currency": row["currency"],
            "currency_explicit": row["currency_explicit"],
            "availability": row["availability"],
            "captured_at": row["captured_at"],
            "source": row["source"],
            "raw_record": dict(row),
        }

    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(raw, Mapping):
            raise TypeError("raw must be a mapping")
        return {
            "raw_name": raw.get("name") or raw.get("title"),
            "brand_raw": raw.get("brand"),
            "size_ml": raw.get("size_ml") or raw.get("sizeml"),
            "concentration": raw.get("concentration"),
            "price": raw.get("price"),
            "currency": raw.get("currency"),
            "availability": raw.get("availability"),
            "product_url": raw.get("product_url") or raw.get("url"),
            "url": raw.get("url") or raw.get("product_url"),
            "external_product_id": raw.get("external_product_id"),
            "gtin": raw.get("gtin"),
            "sku": raw.get("sku"),
            "source": "notino_public_storefront",
            "currency_explicit": raw.get("currency_explicit") is True,
            "captured_at": raw.get("captured_at"),
            "raw_payload": {"public_page": dict(raw)},
        }

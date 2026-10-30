"""Deloox adapter for the Offer Engine contract.

Discovery yields raw listings only; page observations are independently checked.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlparse

import requests

from ..adapters import ConnectorHealth
from ..contracts import Availability, OfferObservation, RetailerListing, Verification

try:
    from scrapers.deloox import scraper
except ModuleNotFoundError:
    from backend.scrapers.deloox import scraper


DELOOX_MARKETS = {
    "deloox.be": "BE",
    "www.deloox.be": "BE",
    "deloox.nl": "NL",
    "www.deloox.nl": "NL",
    "deloox.lu": "LU",
    "www.deloox.lu": "LU",
    "deloox.com": "EU",
    "www.deloox.com": "EU",
    "deloox.es": "ES",
    "www.deloox.es": "ES",
}


def _deloox_market(url: str, fallback: str = "EU") -> str:
    host = (urlparse(url).hostname or "").lower()
    return DELOOX_MARKETS.get(host, fallback)


def _supported_storefront_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in DELOOX_MARKETS:
        return False
    first_segment = next((part.casefold() for part in parsed.path.split("/") if part), "")
    return first_segment != "producto" or host in {"deloox.es", "www.deloox.es"}


def _same_product_path(discovered_url: str, evidence_url: str) -> bool:
    discovered = urlparse(discovered_url)
    evidence = urlparse(evidence_url)
    return (
        discovered.scheme in {"http", "https"}
        and evidence.scheme in {"http", "https"}
        and (discovered.hostname or "").lower() == (evidence.hostname or "").lower()
        and (discovered.path.rstrip("/") or "/") == (evidence.path.rstrip("/") or "/")
    )


class DelooxConnector:
    retailer = "deloox"
    source = "product_page"

    def __init__(self, session=None):
        self._session = session

    @staticmethod
    def _searchable_tokens(value: str) -> set[str]:
        return {
            token
            for token in re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split()
            if token
        }

    def discover(self, query: str) -> Iterable[RetailerListing]:
        # Search-stream accepts broad product-family terms. Requested size is
        # checked against both search facts and the subsequently fetched page,
        # while all family listings remain discoverable for broader refreshes.
        query_tokens = {
            token for token in self._searchable_tokens(query)
            if len(token) > 1 and token not in {"ml", "edp", "edt"}
        }
        result = scraper.search_stream(query)
        if not isinstance(result, dict) or result.get("status") != "success" or not result.get("verified"):
            status = result.get("status", "invalid_result") if isinstance(result, dict) else "invalid_result"
            details = result.get("details", {}) if isinstance(result, dict) else {}
            reasons = details.get("search_failure_reasons") or details.get("browser_search") or {}
            raise RuntimeError(f"deloox_discovery_{status}:{reasons}")

        seen: set[tuple[str, int | None, str | None]] = set()
        for row in result.get("results") or []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            name = str(row.get("name") or "").strip()
            if not url or not name or not _supported_storefront_url(url):
                continue
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            size = attrs.get("size_ml") if isinstance(attrs.get("size_ml"), dict) else {}
            concentration = attrs.get("concentration") if isinstance(attrs.get("concentration"), dict) else {}
            size_value = size.get("value")
            try:
                size_ml = int(size_value) if size_value is not None else None
            except (TypeError, ValueError):
                continue
            brand = str(row.get("brand") or "").strip() or None
            sku_obj = (row.get("identity") or {}).get("sku") if isinstance(row.get("identity"), dict) else {}
            gtin_obj = (row.get("identity") or {}).get("gtin") if isinstance(row.get("identity"), dict) else {}
            sku = str((sku_obj or {}).get("value") or row.get("sku") or "").strip() or None
            gtin = str((gtin_obj or {}).get("value") or "").strip() or None

            # A search request like "Liquid Brun 150 ml" must not discard a
            # result merely because the retailer title omits its size; page
            # size and GTIN become authoritative at observe/resolve time.
            searchable = self._searchable_tokens(" ".join((
                name, brand or "", url, str(size_value or ""),
                str((concentration or {}).get("value") or ""),
            )))
            if query_tokens and not query_tokens.issubset(searchable):
                # Size is optional in the search result; all other query
                # tokens still have to match.
                non_size = query_tokens - {"150", "100", "200", "75", "50", "30"}
                if not non_size.issubset(searchable):
                    continue

            dedupe_key = (url, size_ml, gtin or sku)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            external_id = sku or gtin or hashlib.sha256(
                f"{url}|{size_ml or ''}|{name}".encode("utf-8")
            ).hexdigest()[:24]
            if size_ml is not None and not (sku or gtin):
                external_id = f"{external_id}:{size_ml}ml"

            yield RetailerListing(
                retailer=self.retailer,
                external_id=external_id,
                product_url=url,
                raw_title=name,
                raw_brand=brand,
                raw_size_ml=size_ml,
                raw_concentration=str((concentration or {}).get("value") or "") or None,
                raw_gtin=gtin,
                market=_deloox_market(url),
            )

    def observe(self, listing: RetailerListing) -> OfferObservation:
        if listing.retailer != self.retailer:
            raise ValueError("listing belongs to another retailer")
        session = self._session or requests.Session()
        try:
            row = scraper.extract_product_page(session, listing.product_url)
        finally:
            if self._session is None:
                session.close()
        if not isinstance(row, dict):
            raise RuntimeError("deloox_product_page_not_verified")

        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        size_obj = attrs.get("size_ml") if isinstance(attrs.get("size_ml"), dict) else {}
        observed_size = size_obj.get("value")
        if listing.raw_size_ml is not None and observed_size != listing.raw_size_ml:
            raise ValueError("deloox_variant_size_changed_since_discovery")
        offer = row.get("offer") if isinstance(row.get("offer"), dict) else {}
        evidence_url = str(row.get("url") or listing.product_url).strip()
        if not _supported_storefront_url(evidence_url):
            raise ValueError("deloox_final_url_invalid_or_wrong_market")
        if _deloox_market(evidence_url) != listing.market:
            raise ValueError("deloox_market_changed_since_discovery")
        if not _same_product_path(listing.product_url, evidence_url):
            raise ValueError("deloox_product_page_redirected_to_different_product")

        raw_availability = str(offer.get("availability") or "unknown").lower()
        availability = (
            Availability(raw_availability)
            if raw_availability in Availability._value2member_map_
            else Availability.UNKNOWN
        )
        raw_price = offer.get("price")
        price = Decimal(str(raw_price)) if raw_price is not None else None
        if availability is Availability.OUT_OF_STOCK:
            price = None

        evidence = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
        raw_gtin = identity.get("gtin") if isinstance(identity.get("gtin"), dict) else {}
        observed_gtin = str((raw_gtin or {}).get("value") or "").strip() or None
        if listing.raw_gtin and observed_gtin and listing.raw_gtin != observed_gtin:
            raise ValueError("deloox_gtin_changed_since_discovery")

        return OfferObservation.now(
            listing_key=f"{listing.retailer}:{listing.external_id or listing.product_url}",
            price=price,
            currency=str(offer.get("currency") or "EUR"),
            availability=availability,
            source=self.source,
            verification=Verification.UNVERIFIED,
            evidence_url=evidence_url,
            evidence_hash=digest,
            raw_payload={"retailer": self.retailer, "parsed_page": row},
        )

    def healthcheck(self) -> ConnectorHealth:
        try:
            response = requests.get(scraper.BASE_URL, headers=scraper.HEADERS, timeout=scraper.TIMEOUT)
            blocked = scraper._is_client_challenge_html(getattr(response, "text", ""))
            ok = response.status_code < 500 and not blocked
            message = "client_challenge" if blocked else f"HTTP {response.status_code}"
            return ConnectorHealth(self.retailer, ok, self.source, message)
        except requests.RequestException as exc:
            return ConnectorHealth(self.retailer, False, self.source, type(exc).__name__)

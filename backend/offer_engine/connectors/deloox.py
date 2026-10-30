"""Deloox adapter for the Offer Engine contract.

This adapter reuses the existing retailer-specific parser but emits only raw
listing/observation facts. Canonical IDs are deliberately not assigned here.
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
    """Derive market from the actual storefront host, never from a default."""
    host = (urlparse(url).hostname or "").lower()
    return DELOOX_MARKETS.get(host, fallback)


def _supported_storefront_url(url: str) -> bool:
    """Reject unsupported hosts and Spanish-language /producto/ routes."""
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in DELOOX_MARKETS:
        return False
    first_segment = next((part.casefold() for part in parsed.path.split("/") if part), "")
    # Spanish product routes are valid only on the Spanish storefront.
    return first_segment != "producto" or host in {"deloox.es", "www.deloox.es"}


class DelooxConnector:
    retailer = "deloox"
    source = "product_page"

    def __init__(self, session=None):
        self._session = session

    def discover(self, query: str) -> Iterable[RetailerListing]:
        query_tokens = [
            token for token in re.sub(r"[^a-z0-9]+", " ", str(query or "").casefold()).split()
            if len(token) > 1 and token not in {"ml", "edp", "edt"}
        ]
        result = scraper.search_stream(query)
        if not isinstance(result, dict) or result.get("status") != "success" or not result.get("verified"):
            status = result.get("status", "invalid_result") if isinstance(result, dict) else "invalid_result"
            details = result.get("details", {}) if isinstance(result, dict) else {}
            reasons = details.get("search_failure_reasons") or details.get("browser_search") or {}
            raise RuntimeError(f"deloox_discovery_{status}:{reasons}")
        for row in result.get("results") or []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            name = str(row.get("name") or "").strip()
            if not url or not name or not _supported_storefront_url(url):
                continue
            searchable = re.sub(r"[^a-z0-9]+", " ", f"{name} {row.get('brand') or ''}".casefold())
            if query_tokens and not all(token in searchable.split() for token in query_tokens):
                continue
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            size = attrs.get("size_ml") if isinstance(attrs.get("size_ml"), dict) else {}
            concentration = attrs.get("concentration") if isinstance(attrs.get("concentration"), dict) else {}
            identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
            sku = identity.get("sku") if isinstance(identity.get("sku"), dict) else {}
            gtin = identity.get("gtin") if isinstance(identity.get("gtin"), dict) else {}
            yield RetailerListing(
                retailer=self.retailer,
                external_id=str(sku.get("value") or row.get("sku") or hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]),
                product_url=url,
                raw_title=name,
                raw_brand=str(row.get("brand") or "") or None,
                raw_size_ml=int(size["value"]) if size.get("value") is not None else None,
                raw_concentration=str(concentration.get("value") or "") or None,
                raw_gtin=str(gtin.get("value") or "") or None,
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
        raw_availability = str(offer.get("availability") or "unknown").lower()
        availability = Availability(raw_availability) if raw_availability in Availability._value2member_map_ else Availability.UNKNOWN
        raw_price = offer.get("price")
        price = Decimal(str(raw_price)) if raw_price is not None else None
        evidence = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        # Matching is a separate, reviewed step; a connector never assigns canonical IDs.
        return OfferObservation.now(
            listing_key=f"{listing.retailer}:{listing.external_id or listing.product_url}",
            price=price, currency=str(offer.get("currency") or "EUR"),
            availability=availability, source=self.source, verification=Verification.UNVERIFIED,
            evidence_url=evidence_url, evidence_hash=digest,
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

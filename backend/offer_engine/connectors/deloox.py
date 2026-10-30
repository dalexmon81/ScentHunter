"""Deloox adapter for the Offer Engine contract.

This adapter reuses the existing retailer-specific parser but emits only raw
listing/observation facts. Canonical IDs are deliberately not assigned here.
"""
from __future__ import annotations
import hashlib
import json
from decimal import Decimal
from typing import Iterable
import requests
from backend.offer_engine.adapters import ConnectorHealth
from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.scrapers.deloox import scraper

class DelooxConnector:
    retailer = "deloox"
    source = "product_page"

    def __init__(self, session=None):
        self._session = session

    def discover(self, query: str) -> Iterable[RetailerListing]:
        for row in scraper.search(query) or []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            name = str(row.get("name") or "").strip()
            if not url or not name:
                continue
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            size = attrs.get("size_ml") if isinstance(attrs.get("size_ml"), dict) else {}
            concentration = attrs.get("concentration") if isinstance(attrs.get("concentration"), dict) else {}
            identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
            sku = identity.get("sku") if isinstance(identity.get("sku"), dict) else {}
            gtin = identity.get("gtin") if isinstance(identity.get("gtin"), dict) else {}
            yield RetailerListing(
                retailer=self.retailer,
                external_id=str(sku.get("value") or row.get("sku") or "") or None,
                product_url=url,
                raw_title=name,
                raw_brand=str(row.get("brand") or "") or None,
                raw_size_ml=int(size["value"]) if size.get("value") is not None else None,
                raw_concentration=str(concentration.get("value") or "") or None,
                raw_gtin=str(gtin.get("value") or "") or None,
                market="BE",
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
        raw_availability = str(offer.get("availability") or "unknown").lower()
        availability = Availability(raw_availability) if raw_availability in Availability._value2member_map_ else Availability.UNKNOWN
        raw_price = offer.get("price")
        price = Decimal(str(raw_price)) if raw_price is not None else None
        evidence = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        # Matching is a separate, reviewed step; a connector never assigns canonical IDs.
        return OfferObservation.now(
            listing_key=f"deloox:{listing.external_id or listing.product_url}",
            price=price, currency=str(offer.get("currency") or "EUR"),
            availability=availability, source=self.source, verification=Verification.UNVERIFIED,
            evidence_url=listing.product_url, evidence_hash=digest,
            raw_payload={"retailer": self.retailer, "parsed_page": row},
        )

    def healthcheck(self) -> ConnectorHealth:
        try:
            response = requests.get(scraper.BASE_URL, headers=scraper.HEADERS, timeout=scraper.TIMEOUT)
            return ConnectorHealth(self.retailer, response.status_code < 500, self.source, f"HTTP {response.status_code}")
        except requests.RequestException as exc:
            return ConnectorHealth(self.retailer, False, self.source, type(exc).__name__)

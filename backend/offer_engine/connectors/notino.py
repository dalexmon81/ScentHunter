"""Authorized Notino.fr affiliate-feed connector for the isolated Offer Engine.

The feed is the primary source: no storefront scraping, guessed prices, or
cross-market redirects. Feed rows remain unverified until canonical identity
resolution succeeds in the shared resolver.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ..adapters import ConnectorHealth
from ..contracts import Availability, OfferObservation, RetailerListing, Verification

try:
    from scrapers.notino import affiliate_feed
except ModuleNotFoundError:
    from backend.scrapers.notino import affiliate_feed


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _exact_size_ml(value) -> int | None:
    try:
        size = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not size.is_finite() or size <= 0 or size != size.to_integral_value():
        return None
    return int(size)


def _listing_id(offer) -> str:
    # One parent URL may carry several sizes/GTINs. Keep each sellable variant
    # as a distinct retailer listing so prices cannot overwrite sibling sizes.
    identity = offer.gtin or offer.sku or offer.external_id
    return f"{offer.external_id}:{offer.size_ml:g}ml:{identity}"


class NotinoFeedConnector:
    retailer = "notino"
    source = "feed"
    market = "FR"

    def __init__(self, fetch_feed=None):
        self._fetch_feed = fetch_feed or affiliate_feed._fetch_feed
        self._configured_override = fetch_feed is not None
        self._offers: dict[str, object] = {}

    @staticmethod
    def configured() -> bool:
        return all(os.environ.get(name, "").strip() for name in (
            "NOTINO_CJ_FEED_URL",
            "NOTINO_CJ_FEED_USERNAME",
            "NOTINO_CJ_FEED_PASSWORD",
        ))

    def _load(self):
        payload = self._fetch_feed()
        return affiliate_feed.parse_feed(payload)

    def discover(self, query: str) -> Iterable[RetailerListing]:
        query = str(query or "").strip()
        if not query:
            return []
        if not self._configured_override and not self.configured():
            raise RuntimeError("notino_feed_credentials_missing")
        wanted = [token for token in _norm(query).split() if len(token) > 1]
        if not wanted:
            return []
        requested_size = affiliate_feed._size_ml(query)
        offers = self._load()
        listings = []
        seen = set()
        self._offers = {}
        for offer in offers:
            haystack = set(_norm(f"{offer.brand} {offer.title} {offer.size_ml:g} ml").split())
            if not all(token in haystack for token in wanted):
                continue
            offer_size_ml = _exact_size_ml(offer.size_ml)
            if offer_size_ml is None:
                continue
            if requested_size is not None and abs(offer_size_ml - requested_size) > 0.01:
                continue
            external_id = _listing_id(offer)
            if external_id in seen:
                continue
            seen.add(external_id)
            listing = RetailerListing(
                retailer=self.retailer,
                external_id=external_id,
                product_url=offer.url,
                raw_title=offer.title,
                raw_brand=offer.brand,
                raw_size_ml=offer_size_ml,
                raw_concentration=offer.concentration,
                raw_gtin=offer.gtin,
                market=self.market,
            )
            self._offers[external_id] = offer
            listings.append(listing)
        return listings

    def observe(self, listing: RetailerListing) -> OfferObservation:
        if listing.retailer != self.retailer:
            raise ValueError("listing belongs to another retailer")
        offer = self._offers.get(str(listing.external_id or ""))
        if offer is None:
            raise RuntimeError("notino_feed_listing_not_in_current_discovery")
        offer_size_ml = _exact_size_ml(offer.size_ml)
        if listing.product_url != offer.url or offer_size_ml is None or listing.raw_size_ml != offer_size_ml:
            raise ValueError("notino_feed_listing_identity_changed")
        if listing.raw_gtin and offer.gtin != listing.raw_gtin:
            raise ValueError("notino_feed_gtin_changed")

        raw_availability = str(offer.availability or "").lower()
        if raw_availability == "in_stock":
            availability = Availability.IN_STOCK
            price = Decimal(str(offer.price))
        elif raw_availability == "out_of_stock":
            availability = Availability.OUT_OF_STOCK
            # A sold-out offer is a stock fact, not a purchasable price.
            price = None
        else:
            availability = Availability.UNKNOWN
            price = Decimal(str(offer.price)) if offer.price is not None else None

        evidence = json.dumps(asdict(offer), ensure_ascii=False, sort_keys=True, default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        return OfferObservation.now(
            listing_key=f"{self.retailer}:{listing.external_id}",
            price=price,
            currency=str(offer.currency or "EUR"),
            availability=availability,
            source=self.source,
            verification=Verification.UNVERIFIED,
            evidence_url=offer.url,
            evidence_hash=digest,
            raw_payload={"retailer": self.retailer, "feed_record": asdict(offer)},
        )

    def healthcheck(self) -> ConnectorHealth:
        if not self._configured_override and not self.configured():
            return ConnectorHealth(self.retailer, False, self.source, "notino_feed_credentials_missing")
        try:
            offers = self._load()
            return ConnectorHealth(
                self.retailer,
                bool(offers),
                self.source,
                f"authorized feed parsed: {len(offers)} offers",
            )
        except Exception as exc:
            return ConnectorHealth(self.retailer, False, self.source, type(exc).__name__)

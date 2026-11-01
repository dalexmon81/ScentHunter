"""Amazon Creators API adapter for the isolated Offer Engine.

Only the approved, marketplace-specific Creators API can supply offers. Public
search HTML and search-engine snippets are deliberately not admitted here.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from urllib.parse import urlparse

from ..adapters import ConnectorHealth
from ..contracts import Availability, OfferObservation, RetailerListing, Verification

try:
    from scrapers import amazon_creators_api
    from scrapers.amazon_de import scraper as amazon_de_scraper
    from scrapers.amazon_fr import scraper as amazon_fr_scraper
except ModuleNotFoundError:
    from backend.scrapers import amazon_creators_api
    from backend.scrapers.amazon_de import scraper as amazon_de_scraper
    from backend.scrapers.amazon_fr import scraper as amazon_fr_scraper


class AmazonCreatorsConnector:
    source = "amazon_creators_api"

    def __init__(self, market: str):
        market = str(market or "").strip().lower()
        if market not in {"de", "fr"}:
            raise ValueError("unsupported_amazon_marketplace")
        self.market = market
        self.retailer = f"amazon_{market}"
        self.country = market.upper()
        self._scraper = amazon_de_scraper if market == "de" else amazon_fr_scraper
        self.discovery_details: dict = {}
        self._listings: dict[str, RetailerListing] = {}

    @staticmethod
    def _asin(url: str) -> str | None:
        parsed = urlparse(str(url or ""))
        match = re.fullmatch(r"/(?:dp/|gp/product/)([A-Z0-9]{10})/?", parsed.path, re.I)
        return match.group(1).upper() if match else None

    def discover(self, query: str):
        query = str(query or "").strip()
        self._listings = {}
        if not query:
            self.discovery_details = {"reason": "empty_query", "source": self.source}
            return []
        if not amazon_creators_api.is_configured(self.market):
            self.discovery_details = {"source": self.source, "reason": "creators_api_not_configured"}
            raise RuntimeError(f"{self.retailer}_creators_api_not_configured")

        report = self._scraper.search(query)
        details = report.get("details") if isinstance(report, dict) else {}
        self.discovery_details = dict(details) if isinstance(details, dict) else {}
        if (
            not isinstance(report, dict)
            or report.get("status") != "success"
            or report.get("verified") is not True
            or self.discovery_details.get("source") != self.source
        ):
            status = report.get("status", "invalid_result") if isinstance(report, dict) else "invalid_result"
            raise RuntimeError(f"{self.retailer}_creators_discovery_{status}")

        listings = []
        for row in report.get("results") or []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            parsed = urlparse(url)
            expected_host = f"www.amazon.{self.market}"
            asin = self._asin(url)
            title = str(row.get("name") or "").strip()
            if (
                parsed.scheme != "https"
                or parsed.hostname != expected_host
                or not asin
                or not title
                or str(row.get("store") or "") != self.retailer
                or str(row.get("currency") or "").upper() != "EUR"
            ):
                continue
            try:
                size = int(row["size_ml"]) if row.get("size_ml") is not None else None
            except (TypeError, ValueError):
                size = None
            listing = RetailerListing(
                retailer=self.retailer,
                external_id=asin,
                product_url=url,
                raw_title=title,
                raw_brand=str(row.get("brand") or "").strip() or None,
                raw_size_ml=size,
                raw_concentration=str(row.get("concentration") or "").strip() or None,
                market=self.country,
            )
            self._listings[asin] = listing
            listings.append(listing)
        self.discovery_details["admitted_listing_count"] = len(listings)
        return listings

    def observe(self, listing: RetailerListing) -> OfferObservation:
        if listing.retailer != self.retailer:
            raise ValueError("listing belongs to another Amazon marketplace")
        asin = str(listing.external_id or "").upper()
        if self._listings.get(asin) != listing or self._asin(listing.product_url) != asin:
            raise ValueError("amazon_listing_not_in_current_discovery")

        # GetItems is a second, exact-ASIN read. Search result prices are not
        # persisted; only the current product response can supply the offer.
        row = amazon_creators_api.get_product(
            self.market, asin, self._scraper._size_ml, self._scraper._concentration
        )
        if not isinstance(row, dict):
            raise RuntimeError("amazon_creators_api_product_unavailable")
        evidence_url = str(row.get("url") or "").strip()
        parsed = urlparse(evidence_url)
        expected_host = f"www.amazon.{self.market}"
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected_host
            or self._asin(evidence_url) != asin
            or evidence_url != listing.product_url
        ):
            raise ValueError("amazon_product_url_changed_since_discovery")

        title = str(row.get("name") or "").strip()
        if not title:
            raise RuntimeError("amazon_creators_api_product_title_missing")
        try:
            size = int(row["size_ml"]) if row.get("size_ml") is not None else None
        except (TypeError, ValueError):
            size = None
        if listing.raw_size_ml is not None and size != listing.raw_size_ml:
            raise ValueError("amazon_variant_size_changed_since_discovery")

        try:
            price = Decimal(str(row.get("price_num")))
        except Exception as exc:
            raise RuntimeError("amazon_creators_api_price_missing") from exc
        if not price.is_finite() or price <= 0 or str(row.get("currency") or "").upper() != "EUR":
            raise RuntimeError("amazon_creators_api_price_invalid")

        evidence = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
        digest = "sha256:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
        availability = (
            Availability.IN_STOCK if row.get("available") is True
            else Availability.UNKNOWN
        )
        return OfferObservation.now(
            listing_key=f"{self.retailer}:{asin}",
            price=price,
            currency="EUR",
            availability=availability,
            source=self.source,
            verification=Verification.UNVERIFIED,
            evidence_url=evidence_url,
            evidence_hash=digest,
            raw_payload={"retailer": self.retailer, "creators_api_item": row},
        )

    def healthcheck(self) -> ConnectorHealth:
        configured = amazon_creators_api.is_configured(self.market)
        return ConnectorHealth(
            self.retailer,
            configured,
            self.source,
            "Creators API configured" if configured else "Creators API not configured or comparison not approved",
        )

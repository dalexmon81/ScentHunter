"""Fail-closed placeholder for Perfumes-MEN until written permission is obtained.

The retailer's published terms restrict the site to personal/non-commercial use
and expressly prohibit spidering, crawling and extraction. Do not add a live
scraper or activate this source until the retailer grants written permission
covering automated catalog/price collection and commercial comparison use.
"""
from __future__ import annotations

from typing import Any

from app.connectors.base import ConnectorError, OfferRecord


class PerfumesMemConnector:
    store_key = "perfumesmem"
    source_kind = "permission_blocked"

    _ERROR = "perfumesmem_live_ingestion_blocked_written_permission_required"

    def _blocked(self):
        raise ConnectorError(self._ERROR)

    async def discover_products(self):
        self._blocked()

    async def fetch_product(self, external_id: str):
        self._blocked()

    async def fetch_offers(self, product_key: str):
        self._blocked()

    async def fetch_price_and_stock(self, offer_id: str):
        self._blocked()

    def parse_raw(self, raw: Any):
        self._blocked()

    def validate_offer(self, offer: OfferRecord):
        self._blocked()

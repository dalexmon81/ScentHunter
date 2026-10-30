"""Read-only live regression for Deloox Liquid Brun variants.

This smoke test uses the real retailer search and product-page parser, but never
opens a database connection or writes catalog data.
"""
from __future__ import annotations

import json

from .connectors.deloox import DelooxConnector
from .contracts import Availability
from .resolver import resolve_observation
try:
    from scrapers.deloox import scraper
    from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from scenthunter_next_engine.catalog_repository import CatalogRepository
except ModuleNotFoundError:
    from backend.scrapers.deloox import scraper
    from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


EXPECTED = {
    "1355229": ("SH-0030", "VAR-f87146c82d167f4c", 100),
    "1385920": ("SH-0031", "VAR-f5aff76b4bb5de8a", 150),
}


def run() -> dict[str, object]:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
    matcher = CanonicalMatcher(catalog)
    connector = DelooxConnector()

    listings = list(connector.discover("Liquid Brun"))
    by_id = {listing.external_id: listing for listing in listings if listing.external_id in EXPECTED}
    missing = sorted(set(EXPECTED) - set(by_id))
    if missing:
        raise AssertionError(
            "Deloox live search did not discover expected product IDs: "
            f"{missing}; discovery_state={scraper._LAST_DISCOVERY_STATE}"
        )

    verified: dict[str, object] = {}
    for external_id, (product_id, variant_id, size_ml) in EXPECTED.items():
        listing = by_id[external_id]
        if listing.raw_size_ml != size_ml:
            raise AssertionError(
                f"Deloox listing {external_id} has size {listing.raw_size_ml}, expected {size_ml}"
            )
        if listing.market != "BE" or "deloox.be" not in listing.product_url:
            raise AssertionError(f"Deloox listing {external_id} is not on the Belgian storefront")

        observation = connector.observe(listing)
        resolved = resolve_observation(listing, observation, matcher)
        if resolved.status != "matched":
            raise AssertionError(
                f"Deloox listing {external_id} did not resolve: {resolved.status}/{resolved.reason}"
            )
        if (resolved.observation.product_id, resolved.observation.variant_id) != (product_id, variant_id):
            raise AssertionError(
                f"Deloox listing {external_id} resolved to the wrong canonical variant"
            )
        if resolved.observation.evidence_url is None or "deloox.be" not in resolved.observation.evidence_url:
            raise AssertionError(f"Deloox listing {external_id} has an invalid evidence URL")

        if resolved.observation.availability is Availability.OUT_OF_STOCK:
            if resolved.observation.price is not None:
                raise AssertionError(
                    f"Deloox sold-out {size_ml} ml listing must not carry a price"
                )
        elif resolved.observation.availability is Availability.IN_STOCK:
            if resolved.observation.price is None or resolved.observation.price <= 0:
                raise AssertionError(
                    f"Deloox in-stock {size_ml} ml listing has no valid verified price"
                )
        else:
            raise AssertionError(
                f"Deloox {size_ml} ml listing has unknown stock; refusing to publish an unverified state"
            )

        verified[external_id] = {
            "size_ml": size_ml,
            "product_id": product_id,
            "variant_id": variant_id,
            "market": listing.market,
            "availability": resolved.observation.availability.value,
            "price": str(resolved.observation.price) if resolved.observation.price is not None else None,
            "evidence_url": resolved.observation.evidence_url,
        }

    return {
        "status": "success",
        "mode": "read-only live retailer smoke test",
        "database_accessed": False,
        "catalog_modified": False,
        "products": verified,
    }


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

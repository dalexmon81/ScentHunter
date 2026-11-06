"""Deterministic catalog-first canary and shadow-comparison helpers."""
from __future__ import annotations

import hashlib


def _enabled(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _percent(value, default=0):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(0, min(100, number))


def catalog_rollout_decision(query, rollout_key=None, *, environ=None):
    """Return a stable, fail-closed canary decision.

    SCENTHUNTER_CATALOG_SEARCH_ENABLED is the master switch.
    SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT controls the canary size.
    SCENTHUNTER_CATALOG_SEARCH_SHADOW enables a non-serving catalog read for
    requests that remain on the legacy path.
    """
    env = environ if environ is not None else {}
    enabled = _enabled(env.get("SCENTHUNTER_CATALOG_SEARCH_ENABLED"))
    shadow_enabled = _enabled(env.get("SCENTHUNTER_CATALOG_SEARCH_SHADOW"))

    # The master switch alone never sends traffic to the new path.
    # An explicit percentage is required for every canary stage.
    raw_percent = env.get("SCENTHUNTER_CATALOG_SEARCH_TRAFFIC_PERCENT")
    traffic_percent = _percent(raw_percent, default=0)
    if not enabled:
        traffic_percent = 0

    stable_key = str(rollout_key or query or "").strip()
    digest = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    use_catalog = enabled and bucket < traffic_percent
    run_shadow = shadow_enabled and not use_catalog

    return {
        "enabled": enabled,
        "traffic_percent": traffic_percent,
        "bucket": bucket,
        "use_catalog": use_catalog,
        "run_shadow": run_shadow,
    }


def _identity_key(product):
    if not isinstance(product, dict):
        return None
    brand = str(product.get("canonical_brand") or product.get("brand") or "").strip().casefold()
    name = str(product.get("canonical_name") or product.get("name") or product.get("fragrance") or "").strip().casefold()
    if not brand or not name:
        return None
    return brand, name


def _offer_keys(products):
    keys = set()
    for product in products or []:
        if not isinstance(product, dict):
            continue
        offers = product.get("offers") or []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            store = str(offer.get("store") or offer.get("shop") or "").strip().casefold()
            url = str(offer.get("url") or "").strip().rstrip("/").casefold()
            currency = str(offer.get("currency") or "").strip().upper()
            if store and url:
                keys.add((store, url, currency))
    return keys


def compare_search_payloads(legacy_results, catalog_payload):
    """Compare completed legacy groups with the new catalog-first response."""
    legacy = [row for row in (legacy_results or []) if isinstance(row, dict)]
    catalog = catalog_payload.get("results", []) if isinstance(catalog_payload, dict) else []
    catalog = [row for row in (catalog or []) if isinstance(row, dict)]

    legacy_products = {key for row in legacy if (key := _identity_key(row))}
    catalog_products = {key for row in catalog if (key := _identity_key(row))}
    legacy_offers = _offer_keys(legacy)
    catalog_offers = _offer_keys(catalog)

    shared_products = legacy_products & catalog_products
    shared_offers = legacy_offers & catalog_offers
    return {
        "status": "compared",
        "legacy_product_count": len(legacy_products),
        "catalog_product_count": len(catalog_products),
        "shared_product_count": len(shared_products),
        "legacy_only_product_count": len(legacy_products - catalog_products),
        "catalog_only_product_count": len(catalog_products - legacy_products),
        "legacy_offer_count": len(legacy_offers),
        "catalog_offer_count": len(catalog_offers),
        "shared_offer_count": len(shared_offers),
        "legacy_only_offer_count": len(legacy_offers - catalog_offers),
        "catalog_only_offer_count": len(catalog_offers - legacy_offers),
        "product_overlap_ratio": round(
            len(shared_products) / max(1, len(legacy_products | catalog_products)), 4
        ),
        "offer_overlap_ratio": round(
            len(shared_offers) / max(1, len(legacy_offers | catalog_offers)), 4
        ),
    }

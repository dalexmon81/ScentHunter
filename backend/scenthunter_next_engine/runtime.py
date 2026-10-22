"""Explicitly gated preview route for the isolated next engine.

The route is not mounted unless both opt-in environment flags are enabled.
It is read-only: it does not write to the database or catalog.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException

from .next_engine_service import NextEngineService


def mount_next_engine(app: FastAPI) -> bool:
    """Mount the read-only preview endpoint after the second explicit opt-in."""
    enabled = str(os.environ.get("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "0")).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        print(
            "NEXT_ENGINE_PREVIEW_DISABLED: set SCENTHUNTER_NEXT_PREVIEW_ENABLED=1 "
            "in addition to SCENTHUNTER_NEXT_ENABLED=1 to mount the preview route",
            flush=True,
        )
        return False

    root = Path(__file__).resolve().parents[2]
    catalog_path = root / "backend" / "product_catalog.json"

    def preview_offers(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Preview a batch against the read-only canonical catalog."""
        retailer = payload.get("retailer")
        records = payload.get("records")
        if not isinstance(retailer, str) or not retailer.strip():
            raise HTTPException(status_code=422, detail="retailer must be a non-empty string")
        if not isinstance(records, list):
            raise HTTPException(status_code=422, detail="records must be a JSON array")
        if len(records) > 100:
            raise HTTPException(status_code=413, detail="maximum 100 records per preview")

        try:
            service = NextEngineService.from_catalog_file(catalog_path)
            result = service.process_records(records, retailer=retailer)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="preview_input_or_catalog_error") from exc

        groups = []
        for group in result.groups:
            product = service.catalog.get(group.canonical_product_id)
            groups.append({
                "canonical_product_id": group.canonical_product_id,
                "canonical_variant_id": group.canonical_variant_id,
                "canonical_brand": product.brand if product else None,
                "canonical_name": product.name if product else None,
                "offer_count": len(group.offers),
                "offers": [
                    {
                        "retailer": offer.retailer,
                        "price": str(offer.price) if offer.price is not None else None,
                        "currency": offer.currency,
                        "availability": offer.availability,
                        "product_url": offer.product_url,
                    }
                    for offer in group.offers
                ],
            })

        def unresolved_item(item: Any) -> dict[str, Any]:
            return {
                "retailer": item.offer.retailer,
                "raw_name": item.offer.raw_name,
                "brand_raw": item.offer.brand_raw,
                "size_ml": item.offer.size_ml,
                "status": item.status.value,
                "reason": item.reason,
                "candidate_product_ids": list(item.candidate_product_ids),
            }

        return {
            "mode": "read-only-preview",
            "catalog_modified": False,
            "database_accessed": False,
            "input_count": len(records),
            "normalized_offer_count": result.normalized_offer_count,
            "matched_offer_count": result.matched_offer_count,
            "unresolved": [unresolved_item(item) for item in result.unresolved],
            "ambiguous": [unresolved_item(item) for item in result.ambiguous],
            "rejected_rows": list(result.rejected_rows),
            "groups": groups,
        }

    app.add_api_route(
        "/next-engine/preview",
        preview_offers,
        methods=["POST"],
        tags=["next-engine-preview"],
        name="next_engine_read_only_preview",
    )
    print("NEXT_ENGINE_PREVIEW_MOUNTED: POST /next-engine/preview", flush=True)
    return any(
        getattr(route, "path", None) == "/next-engine/preview"
        and "POST" in (getattr(route, "methods", set()) or set())
        for route in app.routes
    )

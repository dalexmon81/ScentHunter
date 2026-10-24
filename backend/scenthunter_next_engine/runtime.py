"""Explicitly gated preview and shadow routes for the isolated next engine.

Neither route changes normal search behavior. The shadow route reads bounded
candidates from the existing local catalog and compares their identity outcomes
against the new engine; it never calls the scheduler-enabled search_local wrapper.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException

from .next_engine_service import NextEngineService


def mount_next_engine(app: FastAPI) -> bool:
    """Mount read-only Next Engine diagnostics after explicit opt-in."""
    enabled = str(os.environ.get("SCENTHUNTER_NEXT_PREVIEW_ENABLED", "0")).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        print(
            "NEXT_ENGINE_PREVIEW_DISABLED: set SCENTHUNTER_NEXT_PREVIEW_ENABLED=1 "
            "in addition to SCENTHUNTER_NEXT_ENABLED=1 to mount preview routes",
            flush=True,
        )
        return False

    root = Path(__file__).resolve().parents[2]
    catalog_path = root / "backend" / "product_catalog.json"

    def service_or_422() -> NextEngineService:
        try:
            return NextEngineService.from_catalog_file(catalog_path)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="next_engine_catalog_error") from exc

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

    def serialize_result(service: NextEngineService, result: Any) -> dict[str, Any]:
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
        return {
            "normalized_offer_count": result.normalized_offer_count,
            "matched_offer_count": result.matched_offer_count,
            "unresolved": [unresolved_item(item) for item in result.unresolved],
            "ambiguous": [unresolved_item(item) for item in result.ambiguous],
            "rejected_rows": list(result.rejected_rows),
            "groups": groups,
        }

    def preview_offers(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Preview a caller-supplied batch against the canonical catalog."""
        retailer = payload.get("retailer")
        records = payload.get("records")
        if not isinstance(retailer, str) or not retailer.strip():
            raise HTTPException(status_code=422, detail="retailer must be a non-empty string")
        if not isinstance(records, list):
            raise HTTPException(status_code=422, detail="records must be a JSON array")
        if len(records) > 100:
            raise HTTPException(status_code=413, detail="maximum 100 records per preview")

        service = service_or_422()
        try:
            result = service.process_records(records, retailer=retailer)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="preview_input_error") from exc
        return {
            "mode": "read-only-preview",
            "catalog_modified": False,
            "database_accessed": False,
            "input_count": len(records),
            **serialize_result(service, result),
        }

    def shadow_search(q: str, limit: int = 20) -> dict[str, Any]:
        """Compare bounded existing catalog candidates with Next Engine identities."""
        query = str(q or "").strip()
        if not query:
            raise HTTPException(status_code=422, detail="q must be non-empty")
        if len(query) > 200:
            raise HTTPException(status_code=422, detail="q must be at most 200 characters")
        limit = max(1, min(int(limit), 50))

        # Use the pure local-catalog query implementation, not search_local(),
        # which may schedule asynchronous catalog repairs as a side effect.
        try:
            import catalog_engine

            search_impl = getattr(catalog_engine, "_search_local_impl", None)
            if not callable(search_impl):
                raise RuntimeError("local_catalog_query_unavailable")
            rows = search_impl(query, per_store=limit) or []
        except Exception as exc:
            print(f"NEXT_ENGINE_SHADOW_SEARCH_ERROR: {type(exc).__name__}", flush=True)
            raise HTTPException(status_code=503, detail="shadow_catalog_search_unavailable") from exc

        by_retailer: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            retailer = str(row.get("store") or row.get("store_key") or "").strip()
            name = row.get("name") or row.get("product_name") or ""
            if not retailer or not isinstance(name, str) or not name.strip():
                continue
            by_retailer.setdefault(retailer, []).append({
                "name": name,
                "brand": row.get("brand") or row.get("product_brand"),
                "size_ml": row.get("size_ml") or row.get("product_size_ml"),
                "price": row.get("price_num") if row.get("price_num") is not None else row.get("price"),
                "currency": row.get("currency") or "EUR",
                "availability": row.get("availability"),
                "url": row.get("url") or row.get("product_url"),
                "sku": row.get("sku"),
                "image": row.get("image"),
            })

        service = service_or_422()
        retailer_results = []
        for retailer, records in sorted(by_retailer.items()):
            try:
                result = service.process_records(records, retailer=retailer)
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=422, detail="shadow_candidate_mapping_error") from exc
            retailer_results.append({
                "retailer": retailer,
                "candidate_count": len(records),
                **serialize_result(service, result),
            })

        return {
            "mode": "read-only-shadow",
            "query": query,
            "candidate_count": sum(item["candidate_count"] for item in retailer_results),
            "retailer_count": len(retailer_results),
            "database_accessed": True,
            "database_mutated": False,
            "catalog_modified": False,
            "retailers": retailer_results,
            "note": "Diagnostic only; normal /search behavior is unchanged.",
        }

    app.add_api_route(
        "/next-engine/preview",
        preview_offers,
        methods=["POST"],
        tags=["next-engine-preview"],
        name="next_engine_read_only_preview",
    )
    app.add_api_route(
        "/next-engine/search-shadow",
        shadow_search,
        methods=["GET"],
        tags=["next-engine-preview"],
        name="next_engine_read_only_search_shadow",
    )
    print(
        "NEXT_ENGINE_PREVIEW_MOUNTED: POST /next-engine/preview; "
        "GET /next-engine/search-shadow",
        flush=True,
    )
    return any(
        getattr(route, "path", None) == "/next-engine/preview"
        and "POST" in (getattr(route, "methods", set()) or set())
        for route in app.routes
    ) and any(
        getattr(route, "path", None) == "/next-engine/search-shadow"
        and "GET" in (getattr(route, "methods", set()) or set())
        for route in app.routes
    )

"""Legacy product matcher bootstrap isolated from the API entry point."""

import json


def load_product_matcher(matcher_class, catalog_path, family_registry_path):
    """Load the legacy identity matcher from the catalog and optional family registry.

    The catalog remains the primary identity source. The family registry only
    supplements registered legacy families. Failures disable identity matching
    without preventing the API from starting, preserving legacy behavior.
    """
    if matcher_class is None:
        return None

    try:
        with open(catalog_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if isinstance(payload, dict):
            catalog = payload
            product_count = len(payload.get("products") or [])
        elif isinstance(payload, list):
            catalog = payload
            product_count = len(payload)
        else:
            catalog = []
            product_count = 0

        if not product_count:
            print("PRODUCT_MATCHER: catalog empty; identity matching disabled", flush=True)
            return None

        family_registry = None
        if family_registry_path.exists():
            with open(family_registry_path, "r", encoding="utf-8") as handle:
                family_registry = json.load(handle)

        return matcher_class(
            catalog=catalog,
            family_registry=family_registry,
        )
    except Exception as exc:
        print(
            f"PRODUCT_MATCHER_INIT_ERROR: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return None

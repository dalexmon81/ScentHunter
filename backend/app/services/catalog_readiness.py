"""Pure catalog readiness and per-retailer coverage rules."""

def catalog_has_indexed_store(statuses, stores):
    """True when at least one configured store has indexed catalog URLs."""
    statuses = statuses or {}
    for store in stores:
        state = statuses.get(store) or {}
        value = state.get("valid_indexed_urls", state.get("indexed_urls", 0))
        try:
            if int(value or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def stores_missing_indexed_catalog(statuses, stores):
    """Return configured stores without valid indexed catalog URLs."""
    statuses = statuses or {}
    missing = []
    for store in stores:
        state = statuses.get(store) or {}
        value = state.get("valid_indexed_urls", state.get("indexed_urls", 0))
        try:
            indexed = int(value or 0)
        except (TypeError, ValueError):
            indexed = 0
        if indexed <= 0:
            missing.append(store)
    return missing

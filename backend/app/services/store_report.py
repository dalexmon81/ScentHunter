"""Small constructors for normalized store-search reports."""


def empty_store_report(store, status="error", elapsed=0.0, error=None):
    """Build the standard unverified empty report without implying no-match."""
    return {
        "store": store,
        "status": status,
        "elapsed": round(elapsed, 3),
        "count": 0,
        "results": [],
        "error": error,
        "verified": False,
    }

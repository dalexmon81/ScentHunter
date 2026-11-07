"""Normalize legacy scraper returns at both API and worker boundaries."""


def normalize_scraper_report(raw):
    """Return a stable report without inventing a successful empty match."""
    if isinstance(raw, dict):
        results = raw.get("results")
        if results is None:
            results = raw.get("products")
        if not isinstance(results, list):
            results = []
        status = str(raw.get("status") or "").strip().lower()
        if status not in {
            "success", "partial", "error", "timeout", "blocked", "unavailable"
        }:
            status = "success"
        details = raw.get("details") or {}
        verified = bool(raw.get("verified")) if "verified" in raw else (
            status == "success"
        )
        if isinstance(details, dict) and "verified" in details:
            verified = bool(details.get("verified"))
        return {
            "status": status,
            "verified": verified,
            "results": [row for row in results if isinstance(row, dict)],
            "error": raw.get("error"),
            "details": details,
        }

    if isinstance(raw, (list, tuple)):
        rows = [row for row in raw if isinstance(row, dict)]
        return {
            "status": "success" if rows else "unavailable",
            "verified": bool(rows),
            "results": rows,
            "error": None if rows else "legacy_scraper_returned_unverified_empty_list",
            "details": {},
        }

    if raw is None:
        return {
            "status": "error",
            "verified": False,
            "results": [],
            "error": "scraper_returned_none",
            "details": {},
        }

    try:
        values = list(raw)
    except TypeError:
        values = []
    rows = [row for row in values if isinstance(row, dict)]
    return {
        "status": "success",
        "verified": bool(rows),
        "results": rows,
        "error": None,
        "details": {},
    }

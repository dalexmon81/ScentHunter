"""Pure retry decisions for legacy store-search reports."""


def should_retry_store_report(report):
    """Retry only ambiguous, unverified outcomes; never retry technical failures."""
    if not isinstance(report, dict):
        return True

    status = report.get("status")
    if status in {"timeout", "error", "blocked", "unavailable", "cancelled"}:
        return False

    verified = bool(report.get("verified"))
    count = int(report.get("count") or 0)
    if verified and (
        status in {"ok", "no_match"}
        or (status == "partial" and count > 0)
    ):
        return False

    return True

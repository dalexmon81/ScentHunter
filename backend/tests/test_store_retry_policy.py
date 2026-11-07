from app.services.store_retry_policy import should_retry_store_report


def test_technical_failures_are_not_retried():
    for status in ("timeout", "error", "blocked", "unavailable", "cancelled"):
        assert should_retry_store_report({"status": status, "verified": False}) is False


def test_verified_success_and_no_match_are_final():
    assert should_retry_store_report({"status": "ok", "verified": True, "count": 2}) is False
    assert should_retry_store_report({"status": "no_match", "verified": True, "count": 0}) is False


def test_verified_partial_with_results_is_final():
    assert should_retry_store_report({"status": "partial", "verified": True, "count": 1}) is False


def test_ambiguous_or_unverified_outcomes_can_be_retried():
    assert should_retry_store_report({"status": "partial", "verified": True, "count": 0}) is True
    assert should_retry_store_report({"status": "success", "verified": False, "count": 0}) is True
    assert should_retry_store_report(None) is True

from datetime import timezone

import pytest

from scripts.manage_store_authorization import (
    parse_aware_datetime,
    parse_scopes,
    validate_evidence_url,
)


def test_authorization_cli_requires_data_scope_for_discovery_and_refresh():
    with pytest.raises(ValueError, match="price_stock_scope_requires_offer_data_scope"):
        parse_scopes(["price_stock"])
    with pytest.raises(ValueError, match="product_discovery_scope_requires_offer_data_scope"):
        parse_scopes(["product_discovery"])


def test_authorization_cli_normalizes_and_deduplicates_scopes():
    assert parse_scopes(["offer_data", "product_discovery", "offer_data"]) == [
        "offer_data", "product_discovery"
    ]


def test_authorization_cli_rejects_unknown_scopes():
    with pytest.raises(ValueError, match="unsupported_authorization_scope"):
        parse_scopes(["offer_data", "unrestricted_crawl"])


def test_authorization_cli_requires_timezone_aware_timestamps():
    with pytest.raises(ValueError, match="timestamp_must_include_timezone_offset"):
        parse_aware_datetime("2026-11-07T12:00:00")
    parsed = parse_aware_datetime("2026-11-07T12:00:00+01:00")
    assert parsed is not None
    assert parsed.tzinfo == timezone.utc


def test_authorization_cli_requires_https_evidence_url():
    assert validate_evidence_url("https://example.com/consent") == "https://example.com/consent"
    with pytest.raises(ValueError, match="evidence_url_must_be_https"):
        validate_evidence_url("http://example.com/consent")

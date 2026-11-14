"""Regression guards for the read-only Hawas Ice diagnostic."""

from pathlib import Path


def _route():
    source = Path("backend/main.py").read_text(encoding="utf-8")
    return source.split(
        "def diagnose_hawas_ice_offers_read_only():", 1
    )[1].split("@app.get('/search-start')", 1)[0]


def test_hawas_ice_live_vs_persisted_diagnostic_uses_canonical_url():
    route = _route()
    assert (
        "https://www.parfum-zentrum.de/"
        "rasasi-hawas-ice-eau-de-parfum-100-ml-man_z913265/"
    ) in route
    assert "rasasi-hawas-hawas-ice-eau-de-parfum" not in route


def test_hawas_ice_diagnostic_uses_read_only_short_timeout_connection():
    route = _route()
    assert "conn = ce._search_db()" in route
    assert "conn = catalog_db()" not in route


def test_hawas_ice_diagnostic_bounds_total_and_per_store_network_time():
    route = _route()
    assert "diagnostic_deadline = started + 15.0" in route
    assert "live_request_timeout = 4.0" in route
    assert "timeout=min(live_request_timeout, remaining)" in route
    assert "diagnostic_time_budget_exhausted" in route

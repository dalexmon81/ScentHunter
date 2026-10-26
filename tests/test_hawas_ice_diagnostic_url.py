"""Regression guard for the canonical Parfum-Zentrum Hawas Ice diagnostic URL."""

from pathlib import Path


def test_hawas_ice_live_vs_persisted_diagnostic_uses_canonical_url():
    source = Path("backend/main.py").read_text(encoding="utf-8")
    route = source.split(
        "def diagnose_hawas_ice_offers_read_only():", 1
    )[1].split("@app.get('/search-start')", 1)[0]

    assert (
        "https://www.parfum-zentrum.de/"
        "rasasi-hawas-ice-eau-de-parfum-100-ml-man_z913265/"
    ) in route
    assert "rasasi-hawas-hawas-ice-eau-de-parfum" not in route

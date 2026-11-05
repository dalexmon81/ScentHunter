from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures/bplatz/liquid-brun-100ml-user-observation.json"


def test_user_screenshot_observation_is_separate_from_live_offer_evidence():
    observation = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert observation["source"] == "user_provided_screenshot"
    assert observation["observed_at"] is None
    assert observation["product"]["title"] == (
        "French Avenue Liquid Brun Eau de Parfum 100ml"
    )
    assert observation["product"]["brand_from_title"] == "French Avenue"
    assert observation["product"]["localized_brand_label"] == "Viale Francese"
    assert observation["product"]["concentration"] == "Eau de Parfum"
    assert observation["product"]["size_ml"] == 100
    assert observation["product"]["article_number"] == "6290360375694"
    assert observation["product"]["gtin"] == "6290360375694"

    offer = observation["offer"]
    assert Decimal(offer["price"]) == Decimal("27.50")
    assert offer["currency"] == "EUR"
    assert Decimal(offer["previous_price"]) == Decimal("35.00")
    assert offer["displayed_discount_percent"] == 21

    # The screenshot does not prove stock status or a product URL.
    assert any("Availability" in item for item in observation["limitations"])
    assert any("Product URL" in item for item in observation["limitations"])
    assert any("hardcode" in item for item in observation["limitations"])

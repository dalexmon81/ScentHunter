from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OVERLAY = BACKEND / "catalog_overlays" / "arabian_fragrance_discovery_2026-11-07.json"
sys.path.insert(0, str(BACKEND))

from scripts.seed_catalog import merge_discovery_overlay, validate_catalog


def test_researched_arabian_fragrance_overlay_contains_expected_brands_and_identities():
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert overlay["data_kind"] == "candidate_fragrance_identities_only_no_variants_no_offers"
    by_brand = {row["brand_name"]: row["products"] for row in overlay["brands"]}
    assert set(by_brand) == {
        "Velixir", "Mykonos", "Maison Asrar", "Khadlaj", "Bujairami",
        "Paris Corner", "Assaf", "Al Wataniah", "Armaf", "French Avenue",
        "Arabiyat Prestige", "Gulf Orchid", "Swiss Arabian",
    }
    assert sum(len(names) for names in by_brand.values()) == 1186
    assert len({(brand, name.casefold()) for brand, names in by_brand.items() for name in names}) == 1186
    assert {"Monarch", "Majesty", "Treasure", "Imperial", "Vanguard"}.issubset(set(by_brand["Maison Asrar"]))
    assert {"Liquid Brun", "Vulcan Feu"}.issubset(set(by_brand["French Avenue"]))
    assert {"Adonis", "Panacea", "Ether", "Orpheus"}.issubset(set(by_brand["Velixir"]))


def test_overlay_merges_identities_only_and_is_idempotent():
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    raw = {"brands": [], "products": [], "variants": []}

    added = merge_discovery_overlay(raw, overlay)
    assert added == 1186
    assert len(raw["products"]) == 1186
    assert len(raw["brands"]) == 13
    assert raw["variants"] == []
    assert all("gtin" not in row and "size_ml" not in row for row in raw["products"])
    assert all("price" not in row and "url" not in row for row in raw["products"])

    # Reapplying the same overlay must not duplicate product or brand identities.
    assert merge_discovery_overlay(raw, overlay) == 0
    assert len(raw["products"]) == 1186
    assert len(raw["brands"]) == 13

    products, by_product, blocked = validate_catalog(raw)
    assert blocked == []
    assert len(products) == 1186
    assert len(by_product) == 0

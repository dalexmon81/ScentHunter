from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OVERLAY = BACKEND / "catalog_overlays" / "arabian_fragrance_discovery_2026-11-07.json"
sys.path.insert(0, str(BACKEND))

from scripts.seed_catalog import merge_discovery_overlay, validate_catalog


EXPECTED_BRANDS = {
    "Velixir", "Mykonos", "Maison Asrar", "Khadlaj", "Bujairami",
    "Paris Corner", "Assaf", "Al Wataniah", "Armaf", "French Avenue",
    "Arabiyat Prestige", "Gulf Orchid", "Swiss Arabian", "Games of Spades",
    "Lattafa", "Afnan", "Maison Alhambra", "Zimaya", "Al Haramain",
}


def test_researched_fragrance_overlay_contains_requested_brands_and_lines():
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert overlay["data_kind"] == "candidate_fragrance_identities_only_no_variants_no_offers"
    by_brand = {row["brand_name"]: row["products"] for row in overlay["brands"]}
    assert set(by_brand) == EXPECTED_BRANDS
    assert sum(len(names) for names in by_brand.values()) == 2280
    assert all(len(names) == len({name.casefold() for name in names}) for names in by_brand.values())

    assert {"Monarch", "Majesty", "Treasure", "Imperial", "Vanguard"}.issubset(set(by_brand["Maison Asrar"]))
    assert {"Liquid Brun", "Vulcan Feu"}.issubset(set(by_brand["French Avenue"]))
    assert {"Adonis", "Panacea", "Ether", "Orpheus"}.issubset(set(by_brand["Velixir"]))
    assert {"Aromatix Teas Me", "Aromatix Forbidden Fruit", "Aromatix Frostbite", "Aromatix Magnetiq", "Aromatix Naughty Dates",
            "Aromatix Platine Blanc", "Aromatix Royal Taboo", "Aromatix Sun Kissed", "Aromatix X Xandal"}.issubset(set(by_brand["French Avenue"]))
    assert {"King", "Queen", "WildCard", "Full House", "Bid"}.issubset(set(by_brand["Games of Spades"]))
    assert {"Khamrah", "Yara", "Asad"}.issubset(set(by_brand["Lattafa"]))


def test_overlay_merges_identities_only_and_is_idempotent():
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    raw = {"brands": [], "products": [], "variants": []}

    added = merge_discovery_overlay(raw, overlay)
    expected = sum(len(row["products"]) for row in overlay["brands"])
    assert added == expected == 2280
    assert len(raw["products"]) == expected
    assert len(raw["brands"]) == len(EXPECTED_BRANDS)
    assert raw["variants"] == []
    assert all("gtin" not in row and "size_ml" not in row for row in raw["products"])
    assert all("price" not in row and "url" not in row for row in raw["products"])

    assert merge_discovery_overlay(raw, overlay) == 0
    assert len(raw["products"]) == expected
    assert len(raw["brands"]) == len(EXPECTED_BRANDS)

    products, by_product, blocked = validate_catalog(raw)
    assert blocked == []
    assert len(products) == expected
    assert len(by_product) == 0

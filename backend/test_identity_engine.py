"""Regression tests for ScentHunter's generic canonical identity path."""
from __future__ import annotations

import importlib.util
from pathlib import Path

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("scenthunter_main", BASE / "ScentHunter_main.py")
main = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(main)


def resolve(brand, name, query):
    return main._validate_candidate(
        {
            "store": "test-store",
            "brand": brand,
            "name": name,
            "price": "29.99 €",
            "url": "https://example.test/product",
        },
        query,
    )


def test_family_alias_recovers_canonical_brand():
    result = resolve("Hawas", "Hawas Eau de Parfum 100 ml", "Hawas")
    assert result is not None
    assert result["canonical_brand"] == "Rasasi"
    assert result["canonical_name"] == "Hawas"
    assert result["family_id"] == "rasasi_hawas"


def test_registered_gender_variants_are_not_collapsed():
    her = resolve("Hawas", "Hawas For Her Eau de Parfum 100 ml", "Hawas")
    him = resolve("Hawas", "Hawas For Him Eau de Parfum 100 ml", "Hawas")
    assert her is not None and him is not None
    assert her["canonical_brand"] == him["canonical_brand"] == "Rasasi"
    assert her["canonical_name"] == "Hawas for Her"
    assert him["canonical_name"] == "Hawas for Him"
    assert her["canonical_name"] != him["canonical_name"]


def test_wrong_retailer_brand_is_recoverable_when_unrecognized():
    result = resolve("Liquid Brun", "Liquid Brun Men Eau de Parfum 100 ml", "Liquid Brun")
    assert result is not None
    assert result["canonical_brand"] == "French Avenue"
    assert result["canonical_name"] == "Liquid Brun"
    assert result["family_id"] == "french_avenue_liquid_brun"


def test_known_conflicting_brand_is_not_forced():
    result = resolve("Dior", "Hawas", "Hawas")
    assert result is None


def test_retailer_metadata_is_preserved_separately():
    result = resolve("Hawas", "Hawas Eau de Parfum 100 ml", "Hawas")
    assert result is not None
    assert result["retailer_data"]["brand"] == "Hawas"
    assert result["retailer_data"]["name"] == "Hawas Eau de Parfum 100 ml"


if __name__ == "__main__":
    tests = [
        test_family_alias_recovers_canonical_brand,
        test_registered_gender_variants_are_not_collapsed,
        test_wrong_retailer_brand_is_recoverable_when_unrecognized,
        test_known_conflicting_brand_is_not_forced,
        test_retailer_metadata_is_preserved_separately,
    ]
    for test in tests:
        test()
    print(f"PASS: {len(tests)} identity regression tests")

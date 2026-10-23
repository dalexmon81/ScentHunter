"""Guardrails for reviewed GTIN-to-canonical-variant evidence."""
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "backend" / "product_catalog.json"
REGISTRY_PATH = (
    ROOT
    / "backend"
    / "scenthunter_next_engine"
    / "verified_gtin_variant_map.json"
)


def _valid_gtin13(value):
    if not isinstance(value, str) or len(value) != 13 or not value.isdigit():
        return False
    weighted_sum = sum(
        int(digit) * (3 if index % 2 else 1)
        for index, digit in enumerate(value[:12])
    )
    return (10 - weighted_sum % 10) % 10 == int(value[-1])


def test_verified_gtin_registry_has_unique_valid_codes_and_evidence():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    records = registry["records"]
    gtins = [record["gtin"] for record in records]

    assert len(gtins) == len(set(gtins)), "A GTIN must not map ambiguously"
    for record in records:
        assert _valid_gtin13(record["gtin"]), record["gtin"]
        assert record["gtin_type"] == "GTIN-13"
        assert record["status"] == "verified"
        assert record["source_urls"], record["gtin"]
        assert all(url.startswith("https://") for url in record["source_urls"])
        assert record["size_ml"] > 0


def test_verified_gtin_targets_exist_and_match_catalog_variant_facts():
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = {item["product_id"]: item for item in catalog["products"]}
    variants = {item["variant_id"]: item for item in catalog["variants"]}
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    for record in registry["records"]:
        product = products.get(record["product_id"])
        variant = variants.get(record["variant_id"])
        assert product is not None, record["gtin"]
        assert variant is not None, record["gtin"]
        assert variant["product_id"] == record["product_id"], record["gtin"]
        assert variant["size_ml"] == record["size_ml"], record["gtin"]
        assert product["concentration"].casefold() == record["concentration"].casefold(), record["gtin"]
        assert record["refill"] is False, (
            "A bottle GTIN must not be silently reused for a refill pack",
            record["gtin"],
        )

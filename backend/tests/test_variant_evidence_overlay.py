import pytest

from scripts.seed_catalog import merge_variant_evidence_overlay


def test_variant_evidence_overlay_adds_only_documented_sizes_and_concentrations():
    raw = {
        "products": [
            {"product_id": "discovery:velixir:adonis", "brand_name": "Velixir", "canonical_name": "Adonis"},
            {"product_id": "discovery:paris-corner:oravea", "brand_name": "Paris Corner", "canonical_name": "Oravéa"},
        ],
        "variants": [],
    }
    overlay = {
        "products": [
            {
                "brand": "Velixir",
                "fragrance": "Adonis",
                "source_url": "https://velixirperfumes.eu/perfumes/",
                "variants": [
                    {"concentration": "Eau de Parfum", "size_ml": 35},
                    {"concentration": "Eau de Parfum", "size_ml": 100},
                ],
            },
            {
                "brand": "Paris Corner",
                "fragrance": "Oravéa",
                "source_url": "https://www.pariscornerperfumes.com/products/oravea",
                "variants": [{"concentration": "Eau de Parfum", "size_ml": 100}],
            },
        ]
    }

    added = merge_variant_evidence_overlay(raw, overlay)

    assert added == 3
    assert {row["size_ml"] for row in raw["variants"] if row["product_id"].endswith("adonis")} == {35, 100}
    oravea = next(row for row in raw["variants"] if row["product_id"].endswith("oravea"))
    assert oravea["concentration"] == "Eau de Parfum"
    assert next(row for row in raw["variants"] if row["product_id"].endswith("adonis"))["canonical_key"] == "velixir|adonis|edp|35|standard"
    assert oravea["evidence_url"].endswith("/products/oravea")
    assert all(row["is_tester"] is False and row["is_refill"] is False for row in raw["variants"])


def test_variant_evidence_overlay_refuses_unknown_or_ambiguous_catalog_identity():
    raw = {
        "products": [{"product_id": "x", "brand_name": "Velixir", "canonical_name": "Adonis"}],
        "variants": [],
    }
    overlay = {
        "products": [{
            "brand": "Velixir", "fragrance": "Aphrodite",
            "source_url": "https://velixirperfumes.eu/perfumes/",
            "variants": [{"concentration": "Eau de Parfum", "size_ml": 35}],
        }]
    }
    with pytest.raises(ValueError, match="no exact catalog identity"):
        merge_variant_evidence_overlay(raw, overlay)


def test_variant_evidence_overlay_requires_https_source_and_valid_size():
    raw = {
        "products": [{"product_id": "x", "brand_name": "Velixir", "canonical_name": "Adonis"}],
        "variants": [],
    }
    no_source = {"products": [{
        "brand": "Velixir", "fragrance": "Adonis", "source_url": "http://example.com",
        "variants": [{"concentration": "Eau de Parfum", "size_ml": 35}],
    }]}
    with pytest.raises(ValueError, match="HTTPS evidence URL"):
        merge_variant_evidence_overlay(raw, no_source)

    invalid_size = {"products": [{
        "brand": "Velixir", "fragrance": "Adonis", "source_url": "https://velixirperfumes.eu/perfumes/",
        "variants": [{"concentration": "Eau de Parfum", "size_ml": 0}],
    }]}
    with pytest.raises(ValueError, match="invalid evidenced size"):
        merge_variant_evidence_overlay(raw, invalid_size)


def test_variant_evidence_overlay_is_idempotent():
    raw = {
        "products": [{"product_id": "x", "brand_name": "Velixir", "canonical_name": "Adonis"}],
        "variants": [],
    }
    overlay = {"products": [{
        "brand": "Velixir", "fragrance": "Adonis",
        "source_url": "https://velixirperfumes.eu/perfumes/",
        "variants": [{"concentration": "Eau de Parfum", "size_ml": 35}],
    }]}
    assert merge_variant_evidence_overlay(raw, overlay) == 1
    assert merge_variant_evidence_overlay(raw, overlay) == 0
    assert len(raw["variants"]) == 1


def test_variant_evidence_overlay_resolves_legacy_and_discovery_ids_to_same_identity():
    raw = {
        "products": [
            {"product_id": "legacy-123", "brand_name": "Velixir", "canonical_name": "Adonis"},
            {"product_id": "discovery:velixir:adonis", "brand_name": "Velixir", "canonical_name": "Adonis"},
        ],
        "variants": [],
    }
    overlay = {"products": [{
        "brand": "Velixir", "fragrance": "Adonis",
        "source_url": "https://velixirperfumes.eu/perfumes/",
        "variants": [{"concentration": "Eau de Parfum", "size_ml": 35}],
    }]}
    assert merge_variant_evidence_overlay(raw, overlay) == 1
    assert raw["variants"][0]["product_id"] == "discovery:velixir:adonis"

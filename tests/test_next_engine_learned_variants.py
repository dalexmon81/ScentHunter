"""Regression tests for evidence-backed variants learned from live retailer offers."""
from pathlib import Path

from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.scenthunter_next_engine.models import MatchStatus, RetailerOffer


CASES = (
    ("Dior", "Sauvage Eau de Parfum", 60, "SH-AUTO-0178", "VAR-68603ae4357708fb"),
    ("Rasasi", "Hawas Elixir", 100, "SH-AUTO-0730", "VAR-c72b45a00ad75e57"),
    ("Valentino", "Born in Roma Purple Melancholia Uomo", 50, "SH-FAMILY-a9fbdaefd3d5", "VAR-c27b8b0c807f79f3"),
    ("Rasasi", "Hawas Tropical", 100, "SH-FAMILY-aa11dc284ad3", "VAR-8b6788d0daedb3b5"),
    ("Valentino", "Born in Roma Yellow Dream Uomo", 100, "SH-FAMILY-f7a59a54c6db", "VAR-1306fb65e3319915"),
)


def test_evidence_backed_variants_resolve_to_their_exact_canonical_sizes():
    root = Path(__file__).resolve().parents[1]
    catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
    matcher = CanonicalMatcher(catalog)

    for brand, name, size_ml, product_id, variant_id in CASES:
        offer = RetailerOffer(
            retailer="shadow-regression",
            raw_name=name,
            brand_raw=brand,
            size_ml=size_ml,
            product_url="https://example.test/verified-product",
        )
        result = matcher.match(offer)
        assert result.status is MatchStatus.MATCHED, (name, result.status, result.reason)
        assert result.canonical_product_id == product_id
        assert result.canonical_variant_id == variant_id


def test_evidence_backed_variants_do_not_cross_match_other_sizes():
    root = Path(__file__).resolve().parents[1]
    catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
    matcher = CanonicalMatcher(catalog)

    brand, name, size_ml, product_id, variant_id = CASES[0]
    offer = RetailerOffer(
        retailer="shadow-regression",
        raw_name=name,
        brand_raw=brand,
        size_ml=100,
        product_url="https://example.test/verified-product",
    )
    result = matcher.match(offer)
    assert result.status is not MatchStatus.MATCHED or (
        result.canonical_product_id == product_id
        and result.canonical_variant_id != variant_id
    )

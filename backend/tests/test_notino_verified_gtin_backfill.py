"""The reviewed Notino Dior Sauvage GTINs must resolve to exact EDP variants."""

from pathlib import Path

from scripts.backfill_notino_verified_gtin import VERIFIED_GTINS
from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.offer_normalizer import normalize_offer


def test_four_reviewed_notino_gtins_resolve_to_their_exact_sauvage_edp_variants():
    backend = Path(__file__).resolve().parents[1]
    catalog = CatalogRepository.from_file(backend / "product_catalog.json")
    matcher = CanonicalMatcher(catalog)
    for gtin, expected in VERIFIED_GTINS.items():
        payload = {
            "title": f"Dior Sauvage Eau de Parfum {expected['size_ml']} ml",
            "brand": "DIOR",
            "gtin": gtin,
            "size_ml": expected["size_ml"],
            "price": "69.70",
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "product_url": "https://www.notino.fr" + expected["path"],
        }
        offer = normalize_offer(payload, retailer="Notino", currency_default="EUR")
        matched = matcher.match(offer)
        assert matched.reason == "verified_gtin_exact_variant"
        assert matched.canonical_product_id == "SH-AUTO-0178"
        assert matched.canonical_variant_id == expected["variant_id"]
        assert offer.size_ml == expected["size_ml"]


def test_notino_verified_gtin_registry_contains_exactly_four_edp_sizes():
    assert {item["size_ml"] for item in VERIFIED_GTINS.values()} == {30, 60, 100, 200}
    assert len(VERIFIED_GTINS) == 4

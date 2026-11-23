"""The reviewed Notino Dior Sauvage GTINs must resolve to exact EDP variants."""

from pathlib import Path

from scripts.backfill_notino_verified_gtin import VERIFIED_GTINS, _valid_gtin13
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
        assert matched.reason in {
            "verified_gtin_exact_variant",
            "exact_name_brand_alias_and_size",
        }
        assert _valid_gtin13(gtin)
        assert matched.canonical_product_id == "SH-AUTO-0178"
        assert matched.canonical_variant_id == expected["variant_id"]
        assert offer.size_ml == expected["size_ml"]


def test_notino_verified_gtin_registry_contains_exactly_four_edp_sizes():
    assert {item["size_ml"] for item in VERIFIED_GTINS.values()} == {30, 60, 100, 200}
    assert len(VERIFIED_GTINS) == 4


def test_current_feed_lookup_fetches_only_the_four_reviewed_external_ids():
    import asyncio

    from scripts.backfill_notino_verified_gtin import _fetch_current_feed_records

    class FakeFeedConnector:
        def __init__(self):
            self.requested = []

        async def fetch_product(self, external_product_id):
            self.requested.append(external_product_id)
            for gtin, expected in VERIFIED_GTINS.items():
                if expected["external_product_id"] == external_product_id:
                    return {
                        "external_product_id": external_product_id,
                        "gtin": gtin,
                        "source": "authorized_cj_viv_xml_feed",
                    }
            return None

    connector = FakeFeedConnector()
    records = asyncio.run(_fetch_current_feed_records(connector))

    assert set(records) == set(VERIFIED_GTINS)
    assert set(connector.requested) == {
        item["external_product_id"] for item in VERIFIED_GTINS.values()
    }
    assert len(connector.requested) == 4


def test_current_feed_lookup_rejects_external_id_and_gtin_mismatches():
    import asyncio

    from scripts.backfill_notino_verified_gtin import _fetch_current_feed_records

    class MismatchedFeedConnector:
        async def fetch_product(self, external_product_id):
            return {
                "external_product_id": external_product_id,
                "gtin": "0000000000000",
                "source": "authorized_cj_viv_xml_feed",
            }

    records = asyncio.run(_fetch_current_feed_records(MismatchedFeedConnector()))
    assert records == {}

"""The reviewed Notino Dior Sauvage GTINs map to exact EDP variants."""

from pathlib import Path

from scripts.backfill_notino_verified_gtin import (
    CANONICAL_PRODUCT_ID,
    VERIFIED_GTINS,
    _payload_identity_matches,
    _valid_gtin13,
)
from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.offer_normalizer import normalize_offer


def test_four_reviewed_notino_gtins_resolve_to_exact_catalog_edp_variants():
    backend = Path(__file__).resolve().parents[1]
    catalog = CatalogRepository.from_file(backend / "product_catalog.json")
    product = catalog.get(CANONICAL_PRODUCT_ID)
    assert product is not None
    catalog_variants = {variant.variant_id: variant.size_ml for variant in product.variants}

    titles = {
        "3348901608053": "DIOR Sauvage Eau de Parfum rechargeable pour homme 30 ml",
        "3348901368254": "DIOR Sauvage Eau de Parfum pour homme 60 ml",
        "3348901368247": "DIOR Sauvage Eau de Parfum rechargeable pour homme 100 ml",
        "3348901428545": "DIOR Sauvage Eau de Parfum pour homme 200 ml",
    }
    for gtin, expected in VERIFIED_GTINS.items():
        payload = {
            "external_product_id": expected["external_product_id"],
            "title": titles[gtin],
            "brand": "DIOR",
            "gtin": gtin,
            "size_ml": expected["size_ml"],
            "concentration": "Eau de Parfum",
            "price": "69.70",
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "product_url": "https://www.notino.fr" + expected["path"],
            "url": "https://www.notino.fr" + expected["path"],
            "source": "authorized_cj_viv_xml_feed",
        }
        offer = normalize_offer(payload, retailer="Notino", currency_default="EUR")
        assert _valid_gtin13(gtin)
        assert _payload_identity_matches(payload, expected)
        assert catalog_variants[expected["variant_id"]] == expected["size_ml"]
        assert offer.size_ml == expected["size_ml"]


def test_reviewed_gtin_identity_guard_rejects_wrong_brand_concentration_or_size():
    from scripts.backfill_notino_verified_gtin import _payload_identity_matches

    expected = VERIFIED_GTINS["3348901368247"]
    payload = {
        "title": "DIOR Sauvage Eau de Parfum rechargeable pour homme 100 ml",
        "brand": "DIOR",
        "gtin": "3348901368247",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
    }
    assert _payload_identity_matches(payload, expected)
    assert not _payload_identity_matches({**payload, "brand": "Chanel"}, expected)
    assert not _payload_identity_matches({**payload, "concentration": "Eau de Toilette"}, expected)
    assert not _payload_identity_matches({**payload, "size_ml": 60}, expected)


def test_notino_verified_gtin_registry_contains_exactly_four_edp_sizes():
    assert {item["size_ml"] for item in VERIFIED_GTINS.values()} == {30, 60, 100, 200}
    assert len(VERIFIED_GTINS) == 4


def test_current_feed_lookup_fetches_only_the_four_reviewed_external_ids():
    import asyncio

    from scripts.backfill_notino_verified_gtin import _fetch_current_feed_records

    class FakeFeedConnector:
        def __init__(self):
            self.requested = []

        async def fetch_products_by_ids(self, external_product_ids, *, timeout_seconds):
            self.requested.extend(external_product_ids)
            assert timeout_seconds == 240
            return {
                item["external_product_id"]: {
                    "external_product_id": item["external_product_id"],
                    "gtin": gtin,
                    "source": "authorized_cj_viv_xml_feed",
                }
                for gtin, item in VERIFIED_GTINS.items()
                if item["external_product_id"] in external_product_ids
            }

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
        async def fetch_products_by_ids(self, external_product_ids, *, timeout_seconds):
            assert timeout_seconds == 240
            return {
                external_id: {
                    "external_product_id": external_id,
                    "gtin": "0000000000000",
                    "source": "authorized_cj_viv_xml_feed",
                }
                for external_id in external_product_ids
            }

    records = asyncio.run(_fetch_current_feed_records(MismatchedFeedConnector()))
    assert records == {}


def test_backfill_uses_prefetched_feed_records_without_network_io(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from scripts import backfill_notino_verified_gtin as module

    expected_records = {}
    for gtin, expected in VERIFIED_GTINS.items():
        expected_records[gtin] = {
            "external_product_id": expected["external_product_id"],
            "title": f"DIOR Sauvage Eau de Parfum {expected['size_ml']} ml",
            "brand": "DIOR",
            "gtin": gtin,
            "size_ml": expected["size_ml"],
            "concentration": "Eau de Parfum",
            "price": "69.70",
            "currency": "EUR",
            "currency_explicit": True,
            "availability": "in_stock",
            "product_url": "https://www.notino.fr" + expected["path"],
            "url": "https://www.notino.fr" + expected["path"],
            "source": "authorized_cj_viv_xml_feed",
        }

    class StubCatalog:
        def get(self, product_id):
            assert product_id == CANONICAL_PRODUCT_ID
            return SimpleNamespace(variants=[
                SimpleNamespace(variant_id=item["variant_id"], size_ml=item["size_ml"])
                for item in VERIFIED_GTINS.values()
            ])

    monkeypatch.setattr(module.CatalogRepository, "from_file", lambda _path: StubCatalog())

    def unexpected_fetch(_connector):
        raise AssertionError("prefetched records must prevent remote feed access")

    monkeypatch.setattr(module, "_fetch_current_feed_records", unexpected_fetch)
    summary = module.backfill_verified_notino_gtins(
        object(),
        SimpleNamespace(slug="notino-fr", status="active", domain="notino.fr"),
        catalog_path=tmp_path / "unused.json",
        apply=False,
        feed_records=expected_records,
    )

    assert summary["gtin_candidates"] == 4
    assert summary["database_written"] is False

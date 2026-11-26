from __future__ import annotations

import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Brand, Fragrance, Offer, PriceHistory, ProductVariant, Store
from decimal import Decimal
from app.offers.persistence import promote_offer, record_match, stage_raw_offer
from app.matching.canonical_matching import _gtin, resolve_canonical_variant


class CanonicalMatchingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.store = Store(
            id=uuid4(), name="Notino", slug="notino-fr", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        self.brand = Brand(
            id=uuid4(), name="Dior", slug="dior", normalized_name="dior",
        )
        self.fragrance = Fragrance(
            id=uuid4(), brand_id=self.brand.id, name="Sauvage",
            slug="sauvage",
        )
        self.variant = ProductVariant(
            id=uuid4(), fragrance_id=self.fragrance.id,
            concentration="Eau de Parfum", size_ml=100,
            is_tester=False, is_refill=False, is_gift_set=False, is_mini=False,
            canonical_key="dior|sauvage|edp|100|regular",
        )
        self.session.add_all([self.store, self.brand, self.fragrance, self.variant])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_legacy_ingestion_import_is_same_implementation(self):
        from app.services.connector_ingestion import persist_connector_record as legacy_ingest
        from app.offers.ingestion import persist_connector_record as canonical_ingest
        self.assertIs(legacy_ingest, canonical_ingest)

    def test_legacy_offer_persistence_import_is_same_implementation(self):
        from app.services.ingestion_persistence import promote_offer as legacy_promote
        from app.offers.persistence import promote_offer as canonical_promote
        self.assertIs(legacy_promote, canonical_promote)

    def test_legacy_service_import_is_same_implementation(self):
        from app.services.canonical_matching import resolve_canonical_variant as legacy_resolver
        from app.matching.canonical_matching import resolve_canonical_variant as canonical_resolver
        self.assertIs(legacy_resolver, canonical_resolver)

    def test_exact_gtin_has_priority_and_does_not_need_legacy_ids(self):
        self.variant.gtin = "3348901486392"
        self.session.commit()
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-1",
            record={"gtin": "3348901486392"},
        )
        self.assertEqual(result.match.product_variant_id, self.variant.id)
        self.assertEqual(result.match.method, "gtin_exact")
        self.assertEqual(str(result.match.confidence), "1.000")

    def test_deterministic_variant_match_uses_all_variant_attributes(self):
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-2",
            record={
                "brand_raw": "Christian Dior",
                "raw_name": "Dior Sauvage Eau de Parfum 100 ml",
                "concentration": "EDP",
                "size_ml": 100,
            },
        )
        self.assertEqual(result.match.product_variant_id, self.variant.id)
        self.assertEqual(result.match.method, "deterministic_variant")

    def test_shopify_brand_attribution_title_matches_exact_variant(self):
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SHOPIFY-1",
            record={
                "brand_raw": "Dior",
                "raw_name": "Sauvage by Dior - Men Perfume - EDP - 100 ml",
                "concentration": "EDP",
                "size_ml": 100,
            },
        )
        self.assertEqual(result.match.product_variant_id, self.variant.id)
        self.assertEqual(result.match.method, "deterministic_variant")

    def test_unknown_identity_does_not_guess(self):
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-3",
            record={"brand_raw": "Dior", "raw_name": "Dior Sauvage"},
        )
        self.assertIsNone(result.match)
        self.assertIn("incomplete", result.reason)

    def test_repeated_observation_keeps_one_offer_and_appends_price_history(self):
        first_raw_id = stage_raw_offer(
            self.session, store_id=self.store.id, raw_payload={"source_updated_at": "2026-11-24T04:00:00+00:00"},
            external_product_id="REDELIVERED-1",
        )
        record_match(self.session, ingestion_raw_id=first_raw_id,
                     product_variant_id=self.variant.id, method="gtin_exact")
        first_offer_id = promote_offer(
            self.session, ingestion_raw_id=first_raw_id, price=Decimal("89.90"),
            currency="EUR", url="https://notino.fr/p/duplicate",
            availability="in_stock", source="fixture",
        )
        second_raw_id = stage_raw_offer(
            self.session, store_id=self.store.id, raw_payload={"source_updated_at": "2026-11-24T04:00:00+00:00"},
            external_product_id="REDELIVERED-1",
        )
        record_match(self.session, ingestion_raw_id=second_raw_id,
                     product_variant_id=self.variant.id, method="gtin_exact")
        second_offer_id = promote_offer(
            self.session, ingestion_raw_id=second_raw_id, price=Decimal("89.90"),
            currency="EUR", url="https://notino.fr/p/duplicate",
            availability="in_stock", source="fixture",
        )
        self.assertEqual(first_offer_id, second_offer_id)
        self.assertEqual(
            self.session.query(PriceHistory).filter_by(offer_id=first_offer_id).count(),
            2,
        )

    def test_valid_gtin_accepts_standard_spacing_and_hyphen_formatting(self):
        self.variant.gtin = "3348901486392"
        self.session.commit()
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-FORMATTED-GTIN",
            record={"gtin": "334 890 148 639-2"},
        )
        self.assertEqual(result.match.product_variant_id, self.variant.id)
        self.assertEqual(result.match.method, "gtin_exact")

    def test_gtin_checksum_validation_supports_all_gs1_lengths(self):
        for value in (
            "00000000",
            "000000000000",
            "0000000000000",
            "00000000000000",
        ):
            with self.subTest(value=value):
                self.assertEqual(_gtin(value), value)

    def test_invalid_gtin_check_digit_is_rejected(self):
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-BAD-GTIN",
            record={"gtin": "3348901486393"},
        )
        self.assertIsNone(result.match)
        self.assertEqual(result.reason, "invalid_gtin_or_check_digit")

    def test_valid_gtin_does_not_override_conflicting_brand_or_fragrance(self):
        self.variant.gtin = "3348901486392"
        self.session.commit()
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-CONFLICT",
            record={
                "gtin": "3348901486392",
                "brand_raw": "Chanel",
                "raw_name": "Chanel Bleu de Chanel Eau de Parfum 100 ml",
                "concentration": "Eau de Parfum",
                "size_ml": 100,
            },
        )
        self.assertIsNone(result.match)
        self.assertIn("brand", result.reason)
        self.assertIn("fragrance", result.reason)

    def test_valid_gtin_does_not_override_concentration_or_size_conflict(self):
        self.variant.gtin = "3348901486392"
        self.session.commit()
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="SKU-WRONG-VARIANT",
            record={
                "gtin": "3348901486392",
                "brand_raw": "Dior",
                "raw_name": "Dior Sauvage Eau de Toilette 60 ml",
                "concentration": "Eau de Toilette",
                "size_ml": 60,
            },
        )
        self.assertIsNone(result.match)
        self.assertIn("concentration", result.reason)
        self.assertIn("size_ml", result.reason)

    def test_known_store_external_id_reuses_existing_canonical_association(self):
        offer = Offer(
            id=uuid4(), store_id=self.store.id, product_variant_id=self.variant.id,
            external_product_id="KNOWN-1", url="https://notino.fr/p/1",
            price="89.90", currency="EUR", availability="in_stock",
            source="fixture", status="active",
        )
        self.session.add(offer)
        self.session.commit()
        result = resolve_canonical_variant(
            self.session, store_id=self.store.id, external_product_id="KNOWN-1",
            record={},
        )
        self.assertEqual(result.match.product_variant_id, self.variant.id)
        self.assertEqual(result.match.method, "store_external_id")


if __name__ == "__main__":
    unittest.main()

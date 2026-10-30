"""Transactional persistence boundary for the isolated Offer Engine.

Accepts a DB-API connection (psycopg-compatible). Callers own connection
creation; this repository owns one atomic unit of work and never touches legacy
catalog tables.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .contracts import OfferObservation, RetailerListing, Verification
from .policy import OfferPolicy


class OfferRepository:
    def __init__(self, connection: Any, policy: OfferPolicy | None = None, canonical_catalog: Any | None = None):
        self.connection = connection
        self.policy = policy or OfferPolicy()
        self.canonical_catalog = canonical_catalog

    def _ensure_canonical_identity(self, cursor: Any, product_id: str, variant_id: str) -> None:
        """Persist the exact reviewed catalog records required by current-offer FKs."""
        if self.canonical_catalog is None:
            raise ValueError("verified offers require the canonical catalog repository")
        product = self.canonical_catalog.get(product_id)
        if product is None:
            raise ValueError(f"canonical product is absent from catalog: {product_id}")
        variant = next((item for item in product.variants if item.variant_id == variant_id), None)
        if variant is None:
            raise ValueError(f"canonical variant is absent from product {product_id}: {variant_id}")
        cursor.execute(
            """INSERT INTO sh_products(product_id, brand, canonical_name, concentration)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (product_id) DO UPDATE SET
                 brand=EXCLUDED.brand, canonical_name=EXCLUDED.canonical_name,
                 concentration=EXCLUDED.concentration""",
            (product.product_id, product.brand, product.name, product.concentration),
        )
        if variant.size_ml is None:
            raise ValueError(f"canonical variant has no exact size: {variant_id}")
        labels = " ".join((variant.label or "", *variant.aliases)).casefold()
        package_type = "limited_edition" if "limited edition" in labels else "standard"
        cursor.execute(
            """INSERT INTO sh_variants(variant_id, product_id, size_ml, concentration, package_type)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (variant_id) DO UPDATE SET
                 product_id=EXCLUDED.product_id, size_ml=EXCLUDED.size_ml,
                 concentration=EXCLUDED.concentration, package_type=EXCLUDED.package_type""",
            (variant.variant_id, product.product_id, variant.size_ml, product.concentration, package_type),
        )

    def record(self, listing: RetailerListing, observation: OfferObservation) -> dict[str, Any]:
        expected = f"{listing.retailer}:{listing.external_id or listing.product_url}"
        if observation.listing_key != expected:
            raise ValueError("observation does not belong to listing")
        if observation.verification is Verification.VERIFIED:
            if not observation.product_id or not observation.variant_id:
                raise ValueError("verified observation lacks canonical identity")

        decision = self.policy.evaluate(observation)
        cursor = self.connection.cursor()
        try:
            if observation.verification is Verification.VERIFIED:
                self._ensure_canonical_identity(cursor, observation.product_id, observation.variant_id)
            cursor.execute(
                """INSERT INTO sh_retailers(retailer_id, display_name, market)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (retailer_id) DO NOTHING""",
                (listing.retailer, listing.retailer.title(), listing.market),
            )
            cursor.execute(
                """INSERT INTO sh_retailer_listings
                   (retailer_id, external_id, product_url, market, raw_title, raw_brand,
                    raw_size_ml, raw_concentration, raw_gtin, canonical_product_id,
                    canonical_variant_id, match_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (retailer_id, product_url) DO UPDATE SET
                     last_seen_at=now(),
                     raw_title=EXCLUDED.raw_title,
                     raw_brand=EXCLUDED.raw_brand,
                     raw_size_ml=EXCLUDED.raw_size_ml,
                     raw_concentration=EXCLUDED.raw_concentration,
                     raw_gtin=EXCLUDED.raw_gtin,
                     canonical_product_id=COALESCE(EXCLUDED.canonical_product_id, sh_retailer_listings.canonical_product_id),
                     canonical_variant_id=COALESCE(EXCLUDED.canonical_variant_id, sh_retailer_listings.canonical_variant_id),
                     match_status=CASE WHEN EXCLUDED.match_status='matched' THEN 'matched' ELSE sh_retailer_listings.match_status END
                   RETURNING listing_id""",
                (listing.retailer, listing.external_id, listing.product_url, listing.market,
                 listing.raw_title, listing.raw_brand, listing.raw_size_ml,
                 listing.raw_concentration, listing.raw_gtin,
                 observation.product_id if observation.verification is Verification.VERIFIED else None,
                 observation.variant_id if observation.verification is Verification.VERIFIED else None,
                 "matched" if observation.verification is Verification.VERIFIED else "unresolved"),
            )
            listing_id = cursor.fetchone()[0]
            cursor.execute(
                """INSERT INTO sh_offer_observations
                   (listing_id, observed_at, price, currency, availability, source,
                    verification, evidence_url, evidence_hash, rejection_reason, raw_payload)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                   RETURNING observation_id""",
                (listing_id, observation.observed_at, observation.price, observation.currency,
                 observation.availability.value, observation.source, observation.verification.value,
                 observation.evidence_url, observation.evidence_hash, observation.rejection_reason,
                 json.dumps(observation.raw_payload or {}, ensure_ascii=False, default=str)),
            )
            observation_id = cursor.fetchone()[0]

            published = False
            if decision.publish:
                cursor.execute(
                    """INSERT INTO sh_current_offers
                       (listing_id, observation_id, product_id, variant_id, verified_at)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (listing_id) DO UPDATE SET
                         observation_id=EXCLUDED.observation_id,
                         product_id=EXCLUDED.product_id,
                         variant_id=EXCLUDED.variant_id,
                         verified_at=EXCLUDED.verified_at
                       WHERE EXCLUDED.verified_at >= sh_current_offers.verified_at""",
                    (listing_id, observation_id, observation.product_id,
                     observation.variant_id, observation.observed_at),
                )
                published = cursor.rowcount == 1
            elif observation.verification is Verification.VERIFIED and decision.reason in {"out_of_stock", "price_missing"}:
                # A newer, verified non-purchasable observation must retire an
                # older current offer; otherwise stale prices remain visible.
                cursor.execute(
                    """DELETE FROM sh_current_offers
                       WHERE listing_id=%s AND verified_at <= %s""",
                    (listing_id, observation.observed_at),
                )
            self.connection.commit()
            return {
                "listing_id": listing_id,
                "observation_id": observation_id,
                "published": published,
                "policy_reason": decision.reason,
            }
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

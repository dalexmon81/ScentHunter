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
    def __init__(self, connection: Any, policy: OfferPolicy | None = None):
        self.connection = connection
        self.policy = policy or OfferPolicy()

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
                     raw_gtin=EXCLUDED.raw_gtin
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

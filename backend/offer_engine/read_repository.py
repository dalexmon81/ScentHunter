"""Read-only query model for the isolated Offer Engine current-state table."""
from __future__ import annotations

from typing import Any


class OfferReadRepository:
    """Read the latest verified state, including sold-out variants without prices."""

    def __init__(self, connection: Any):
        self.connection = connection

    def search(
        self,
        query: str,
        *,
        market: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        term = str(query or "").strip()
        if not term:
            raise ValueError("query must not be empty")
        if not 1 <= int(limit) <= 200:
            raise ValueError("limit must be between 1 and 200")
        normalized_market = str(market).strip().upper() if market else None
        pattern = f"%{term}%"

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """SELECT
                       p.product_id,
                       p.brand,
                       p.canonical_name,
                       p.concentration,
                       v.variant_id,
                       v.size_ml,
                       v.package_type,
                       r.retailer_id,
                       r.display_name AS retailer_name,
                       l.market,
                       l.product_url,
                       o.price,
                       o.currency,
                       o.availability,
                       o.observed_at,
                       o.evidence_url
                   FROM sh_current_offers AS current
                   JOIN sh_offer_observations AS o
                     ON o.observation_id=current.observation_id
                    AND o.listing_id=current.listing_id
                   JOIN sh_retailer_listings AS l
                     ON l.listing_id=current.listing_id
                   JOIN sh_retailers AS r
                     ON r.retailer_id=l.retailer_id
                   JOIN sh_products AS p
                     ON p.product_id=current.product_id
                   JOIN sh_variants AS v
                     ON v.variant_id=current.variant_id
                    AND v.product_id=current.product_id
                   WHERE current.verified_at >= now() - (r.max_offer_age_seconds * interval '1 second')
                     AND o.verification = 'verified'
                     AND o.availability IN ('in_stock', 'out_of_stock')
                     AND (
                       p.canonical_name ILIKE %s
                       OR p.brand ILIKE %s
                       OR l.raw_title ILIKE %s
                   )
                     AND (%s::text IS NULL OR l.market=%s)
                   ORDER BY
                       (o.price IS NULL) ASC,
                       o.price ASC NULLS LAST,
                       r.display_name ASC,
                       l.product_url ASC
                   LIMIT %s""",
                (pattern, pattern, pattern, normalized_market, normalized_market, int(limit)),
            )
            rows = cursor.fetchall()
            columns = [
                column.name if hasattr(column, "name") else column[0]
                for column in cursor.description
            ]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            cursor.close()

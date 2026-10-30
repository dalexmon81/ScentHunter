"""Read-only query model for the isolated Offer Engine current-state table."""
from __future__ import annotations

from typing import Any
import re
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class OfferReadRepository:
    """Read the latest verified state, including sold-out variants without prices."""

    def __init__(self, connection: Any):
        self.connection = connection
        self._sqlite = isinstance(connection, sqlite3.Connection)

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
        tokens = re.findall(r"[a-z0-9]+", term.casefold())
        size_parts = term.casefold().replace("ml", " ml").split()
        requested_size = None
        for index, part in enumerate(size_parts):
            if part == "ml" and index > 0 and size_parts[index - 1].isdigit():
                requested_size = int(size_parts[index - 1])
                break
        if requested_size is not None:
            tokens = [token for token in tokens if token not in {str(requested_size), f"{requested_size}ml", "ml"}]
        else:
            tokens = [token for token in tokens if token != "ml"]
        if not tokens and requested_size is None:
            tokens = [term.casefold()]

        cursor = self.connection.cursor()
        try:
            if self._sqlite:
                sql = """SELECT
                           p.product_id, p.brand, p.canonical_name, p.concentration,
                           v.variant_id, v.size_ml, v.package_type,
                           r.retailer_id, r.display_name AS retailer_name,
                           l.market, l.product_url, l.external_id, o.price, o.currency,
                           o.availability, o.observed_at, o.evidence_url
                       FROM sh_current_offers AS current
                       JOIN sh_offer_observations AS o
                         ON o.observation_id=current.observation_id
                        AND o.listing_id=current.listing_id
                       JOIN sh_retailer_listings AS l ON l.listing_id=current.listing_id
                       JOIN sh_retailers AS r ON r.retailer_id=l.retailer_id
                       JOIN sh_products AS p ON p.product_id=current.product_id
                       JOIN sh_variants AS v
                         ON v.variant_id=current.variant_id AND v.product_id=current.product_id
                       WHERE datetime(current.verified_at) >= datetime(
                           'now', '-' || r.max_offer_age_seconds || ' seconds'
                       )
                         AND o.verification='verified'
                         AND o.availability IN ('in_stock','out_of_stock')
                         AND ((o.availability='out_of_stock' AND o.price IS NULL)
                              OR (o.availability='in_stock' AND o.price > 0))
                         AND ({search_clause})
                         {size_clause}
                         AND (? IS NULL OR l.market=?)
                       ORDER BY (o.price IS NULL) ASC, o.price ASC,
                                r.display_name ASC, l.market ASC, p.product_id ASC,
                                v.variant_id ASC, o.observed_at DESC, l.product_url ASC
                       LIMIT ?"""
                search_clause = " AND ".join(
                    "(" + " OR ".join(
                        f"lower(COALESCE({column}, '')) LIKE lower(?)"
                        for column in ("p.canonical_name", "p.brand", "l.raw_title", "v.concentration", "v.package_type")
                    ) + ")"
                    for _ in tokens
                ) or "1=1"
                size_clause = "AND v.size_ml = ?" if requested_size is not None else ""
                sql = sql.format(search_clause=search_clause, size_clause=size_clause)
                search_params = [f"%{token}%" for token in tokens for _ in range(5)]
                if requested_size is not None:
                    search_params.append(requested_size)
                params = tuple(search_params + [normalized_market, normalized_market, int(limit)])
            else:
                sql = """SELECT
                           p.product_id, p.brand, p.canonical_name, p.concentration,
                           v.variant_id, v.size_ml, v.package_type,
                           r.retailer_id, r.display_name AS retailer_name,
                           l.market, l.product_url, l.external_id, o.price, o.currency,
                           o.availability, o.observed_at, o.evidence_url
                       FROM sh_current_offers AS current
                       JOIN sh_offer_observations AS o
                         ON o.observation_id=current.observation_id
                        AND o.listing_id=current.listing_id
                       JOIN sh_retailer_listings AS l ON l.listing_id=current.listing_id
                       JOIN sh_retailers AS r ON r.retailer_id=l.retailer_id
                       JOIN sh_products AS p ON p.product_id=current.product_id
                       JOIN sh_variants AS v
                         ON v.variant_id=current.variant_id AND v.product_id=current.product_id
                       WHERE current.verified_at >= now() - (r.max_offer_age_seconds * interval '1 second')
                         AND o.verification='verified'
                         AND o.availability IN ('in_stock','out_of_stock')
                         AND ((o.availability='out_of_stock' AND o.price IS NULL)
                              OR (o.availability='in_stock' AND o.price > 0))
                         AND ({search_clause})
                         {size_clause}
                         AND (%s::text IS NULL OR l.market=%s)
                       ORDER BY (o.price IS NULL) ASC, o.price ASC NULLS LAST,
                                r.display_name ASC, l.market ASC, p.product_id ASC,
                                v.variant_id ASC, o.observed_at DESC, l.product_url ASC
                       LIMIT %s"""
                search_clause = " AND ".join(
                    "(" + " OR ".join(
                        f"COALESCE({column}, '') ILIKE %s"
                        for column in ("p.canonical_name", "p.brand", "l.raw_title", "v.concentration", "v.package_type")
                    ) + ")"
                    for _ in tokens
                ) or "1=1"
                size_clause = "AND v.size_ml = %s" if requested_size is not None else ""
                sql = sql.format(search_clause=search_clause, size_clause=size_clause)
                search_params = [f"%{token}%" for token in tokens for _ in range(5)]
                if requested_size is not None:
                    search_params.append(requested_size)
                params = tuple(search_params + [normalized_market, normalized_market, int(limit)])
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            columns = [
                column.name if hasattr(column, "name") else column[0]
                for column in cursor.description
            ]
            # A retailer can expose duplicate product pages for the same
            # sellable variant. Keep the best current offer once per retailer,
            # canonical variant and market: in-stock/lowest price wins because
            # the SQL order ranks those rows first; latest observation breaks ties.
            deduplicated: dict[tuple[str, str, str, str], dict[str, Any]] = {}
            for raw_row in rows:
                item = dict(zip(columns, raw_row))
                # Shopify product pages can host multiple variants at one URL.
                # Preserve the exact selected bottle in the customer click-through
                # when the listing key is the numeric Shopify variant ID.
                if (
                    item["retailer_id"] in {"parfumcity", "orioudh", "perfumemarket"}
                    and str(item.get("external_id") or "").isdigit()
                ):
                    parsed_url = urlsplit(str(item["product_url"]))
                    query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
                    query["variant"] = str(item["external_id"])
                    item["product_url"] = urlunsplit((
                        parsed_url.scheme, parsed_url.netloc, parsed_url.path,
                        urlencode(query), parsed_url.fragment,
                    ))
                key = (
                    str(item["retailer_id"]),
                    str(item["product_id"]),
                    str(item["variant_id"]),
                    str(item["market"]),
                )
                deduplicated.setdefault(key, item)
            return list(deduplicated.values())
        finally:
            cursor.close()

"""Deterministic identity resolution for retailer observations.

This first resolver deliberately uses exact, explainable keys only. It never
merges on fuzzy title similarity; uncertain records remain separate until a
reviewed identity rule can safely connect them.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal

from .models import Offer, Product, RetailerOfferRecord, SourceObservation, Variant


def _normalise(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _canonical_product_name(title: str) -> str:
    """Remove explicit trade-item attributes while preserving model/name words."""
    value = str(title or "")
    value = re.sub(r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl|l|oz)\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|eau\s+de\s+cologne|edp|edt|edc|extrait(?:\s+de\s+parfum)?)\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:pack\s+of|set\s+of|lot\s+de|duo)\s*\d*\b", " ", value, flags=re.I)
    return " ".join(value.split()).strip(" -–—,;:") or str(title).strip()


def _key(namespace: str, *parts: str | None) -> str:
    material = "\x1f".join([namespace, *[str(part or "").strip() for part in parts]])
    return f"{namespace}_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


class DeterministicIdentityResolver:
    """Resolve exact identifiers first, then exact brand + normalized name.

    The fallback key is intentionally conservative and transparent. It is not
    a fuzzy deduplication engine; a future reviewed matcher can replace it.
    """

    def resolve(self, record: RetailerOfferRecord) -> SourceObservation:
        brand_key = _normalise(record.brand)
        canonical_name = _canonical_product_name(record.title)
        name_key = _normalise(canonical_name)
        # GTINs and MPNs often identify a specific size/pack, not the abstract
        # fragrance. Keep them on the variant/offer layer, never as product IDs.
        product_key = _key("product", "exact-name", brand_key, name_key)

        product = Product(
            product_id=product_key,
            brand=record.brand.strip(),
            canonical_name=canonical_name,
            gtin=None,
            mpn=None,
        )
        size = Decimal(str(record.size_ml)) if record.size_ml is not None else None
        concentration_key = _normalise(record.concentration)
        gender_key = _normalise(record.gender)
        variant_key = _key(
            "variant", product.product_id, concentration_key,
            str(size.normalize()) if size is not None else None,
            str(record.pack_count), gender_key, record.gtin, record.mpn,
        )
        variant = Variant(
            variant_id=variant_key,
            product_id=product.product_id,
            concentration=record.concentration,
            size_ml=size,
            pack_count=record.pack_count,
            gender=record.gender,
        )
        offer_key = _key("offer", record.store, record.product_url, variant.variant_id)
        offer = Offer(
            offer_id=offer_key,
            variant_id=variant.variant_id,
            store=record.store,
            product_url=record.product_url,
            price_minor=record.price_minor,
            currency=record.currency,
            availability=record.availability,
            observed_at=record.observed_at,
            source_sku=record.sku,
        )
        return SourceObservation(
            store=record.store,
            source_url=record.source_url,
            observed_at=record.observed_at,
            product=product,
            variant=variant,
            offer=offer,
            raw_title=record.title,
            raw_price=record.raw_price,
            parser_version=record.parser_version,
            trace_id=record.trace_id,
        )

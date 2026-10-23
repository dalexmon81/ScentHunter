"""Read-only adapter for ScentHunter's actual product_catalog.json schema.

The canonical catalog is read-only. Product identities live in ``products``;
real variant identities live in the separate top-level ``variants`` array and
are linked by ``product_id``. Explicit product and variant aliases are retained
for exact matching; this module never synthesizes canonical IDs.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import CanonicalProduct, CanonicalVariant


class CatalogFormatError(ValueError):
    """Raised when the catalog cannot be interpreted safely."""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _aliases(value: Any) -> tuple[str, ...]:
    """Keep only non-empty string aliases, preserving order without duplicates."""
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        alias = _text(item)
        if alias and alias not in seen:
            seen.add(alias)
            result.append(alias)
    return tuple(result)


def _positive_int(value: Any) -> int | None:
    """Accept only finite, strictly positive whole-number sizes."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    if number != number.to_integral_value():
        return None
    return int(number)


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


class CatalogRepository:
    """Immutable in-memory view of canonical products and explicit variants."""

    def __init__(
        self,
        products: Iterable[CanonicalProduct],
        source: Path,
        *,
        skipped_product_count: int = 0,
        skipped_variant_count: int = 0,
        source_variant_count: int = 0,
    ) -> None:
        items = tuple(products)
        ids = [item.product_id for item in items]
        if len(ids) != len(set(ids)):
            raise CatalogFormatError("Duplicate canonical product IDs in catalog")
        variant_ids = [
            variant.variant_id
            for product in items
            for variant in product.variants
        ]
        if len(variant_ids) != len(set(variant_ids)):
            raise CatalogFormatError("Duplicate canonical variant IDs in catalog")
        self._products = items
        self._by_id = {item.product_id: item for item in items}
        self.source = source
        self._skipped_product_count = skipped_product_count
        self._skipped_variant_count = skipped_variant_count
        self._source_variant_count = source_variant_count

    @classmethod
    def from_file(cls, path: str | Path) -> "CatalogRepository":
        source = Path(path).expanduser().resolve()
        try:
            with source.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except OSError as exc:
            raise CatalogFormatError(f"Cannot read catalog file: {source}") from exc
        except json.JSONDecodeError as exc:
            raise CatalogFormatError(f"Catalog is not valid JSON: {source}") from exc

        if not isinstance(raw, Mapping):
            raise CatalogFormatError("Catalog root must be a JSON object")

        product_records = _list_of_mappings(raw.get("products"))
        variant_records = _list_of_mappings(raw.get("variants"))
        if not product_records:
            raise CatalogFormatError("Catalog has no records in the top-level products array")
        if "variants" not in raw or not isinstance(raw.get("variants"), list):
            raise CatalogFormatError("Catalog is missing the top-level variants array")

        variants_by_product: dict[str, list[CanonicalVariant]] = {}
        skipped_variants = 0
        for record in variant_records:
            variant_id = _text(record.get("variant_id"))
            product_id = _text(record.get("product_id"))
            if not variant_id or not product_id:
                skipped_variants += 1
                continue
            size_ml = _positive_int(record.get("size_ml"))
            variant_aliases = _aliases(record.get("aliases"))
            label = variant_aliases[0] if variant_aliases else None
            try:
                variant = CanonicalVariant(
                    variant_id=variant_id,
                    size_ml=size_ml,
                    label=label,
                    aliases=variant_aliases,
                )
            except ValueError:
                skipped_variants += 1
                continue
            variants_by_product.setdefault(product_id, []).append(variant)

        products: list[CanonicalProduct] = []
        skipped_products = 0
        seen_product_ids: set[str] = set()
        for record in product_records:
            product_id = _text(record.get("product_id"))
            brand = _text(record.get("brand_name"))
            name = _text(record.get("canonical_name"))
            if not product_id or not brand or not name:
                skipped_products += 1
                continue
            if product_id in seen_product_ids:
                raise CatalogFormatError(f"Duplicate canonical product ID: {product_id}")
            seen_product_ids.add(product_id)
            image_url = _text(record.get("canonical_image"))
            product_aliases = _aliases(record.get("aliases"))
            try:
                products.append(
                    CanonicalProduct(
                        product_id=product_id,
                        brand=brand,
                        name=name,
                        variants=tuple(variants_by_product.get(product_id, ())),
                        canonical_image_url=image_url,
                        aliases=product_aliases,
                    )
                )
            except ValueError:
                skipped_products += 1

        if not products:
            raise CatalogFormatError("No safe canonical products could be parsed")

        orphan_variant_ids = {
            _text(record.get("variant_id"))
            for record in variant_records
            if _text(record.get("product_id")) not in seen_product_ids
        }
        orphan_variant_ids.discard(None)
        skipped_variants += len(orphan_variant_ids)

        return cls(
            products,
            source,
            skipped_product_count=skipped_products,
            skipped_variant_count=skipped_variants,
            source_variant_count=len(variant_records),
        )

    def get(self, product_id: str) -> CanonicalProduct | None:
        """Return a product by its exact canonical ID."""
        return self._by_id.get(str(product_id))

    def all_products(self) -> tuple[CanonicalProduct, ...]:
        """Return all successfully parsed canonical products."""
        return self._products

    def product_count(self) -> int:
        return len(self._products)

    def skipped_product_count(self) -> int:
        return self._skipped_product_count

    def source_variant_count(self) -> int:
        return self._source_variant_count

    def skipped_variant_count(self) -> int:
        return self._skipped_variant_count

    def variant_count(self) -> int:
        return sum(len(product.variants) for product in self._products)

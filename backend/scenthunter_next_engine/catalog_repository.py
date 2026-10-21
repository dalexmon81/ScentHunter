"""Read-only adapter for the existing ScentHunter canonical product catalog.

This module deliberately does not write to product_catalog.json or to SQLite.
Because the legacy catalog schema has evolved, parsing is defensive: unknown
shapes are reported instead of silently inventing product or variant IDs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import CanonicalProduct, CanonicalVariant


class CatalogFormatError(ValueError):
    """Raised when the catalog cannot be interpreted safely."""


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(float(str(value).strip()))
    except (ValueError, TypeError, OverflowError):
        return None
    return number if number > 0 else None


def _records(value: Any) -> list[Mapping[str, Any]]:
    """Return dictionary records from a list or a dictionary of records."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, dict):
        if any(key in value for key in ("id", "product_id", "catalog_id", "name")):
            return [value]
        return [item for item in value.values() if isinstance(item, Mapping)]
    return []


class CatalogRepository:
    """Immutable in-memory view of canonical products loaded from JSON."""

    def __init__(self, products: Iterable[CanonicalProduct], source: Path) -> None:
        items = tuple(products)
        ids = [item.product_id for item in items]
        if len(ids) != len(set(ids)):
            raise CatalogFormatError("Duplicate canonical product IDs in catalog")
        self._products = items
        self._by_id = {item.product_id: item for item in items}
        self.source = source

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

        product_source = _first(raw, "products", "catalog", "items")
        if product_source is None:
            # Some catalog exports are grouped by brand.
            brands = raw.get("brands")
            if isinstance(brands, list):
                gathered: list[Mapping[str, Any]] = []
                for brand_record in brands:
                    if not isinstance(brand_record, Mapping):
                        continue
                    brand_name = _as_text(_first(brand_record, "name", "brand"))
                    nested = _records(_first(brand_record, "products", "items"))
                    for item in nested:
                        item_copy = dict(item)
                        if brand_name and not _first(item_copy, "brand", "brand_name"):
                            item_copy["brand"] = brand_name
                        gathered.append(item_copy)
                product_source = gathered

        records = _records(product_source)
        if not records:
            raise CatalogFormatError(
                "No product records found in the catalog's recognized structures"
            )

        products: list[CanonicalProduct] = []
        skipped: list[str] = []
        for index, record in enumerate(records):
            product_id = _as_text(_first(record, "id", "product_id", "catalog_id", "canonical_id"))
            name = _as_text(_first(record, "name", "product_name", "title"))
            brand = _as_text(_first(record, "brand", "brand_name", "manufacturer"))
            if not product_id or not name or not brand:
                skipped.append(f"record {index}: missing product ID, brand, or name")
                continue

            variant_source = _first(record, "variants", "sizes", "formats")
            variants: list[CanonicalVariant] = []
            for variant_index, variant in enumerate(_records(variant_source)):
                variant_id = _as_text(
                    _first(variant, "id", "variant_id", "canonical_variant_id")
                )
                if not variant_id:
                    # Never synthesize a canonical variant identifier.
                    continue
                size_ml = _as_positive_int(
                    _first(variant, "size_ml", "volume_ml", "format_ml", "ml", "size")
                )
                label = _as_text(_first(variant, "label", "name", "format", "display_name"))
                try:
                    variants.append(
                        CanonicalVariant(
                            variant_id=variant_id,
                            size_ml=size_ml,
                            label=label or f"variant {variant_index + 1}",
                        )
                    )
                except ValueError:
                    continue

            image_url = _as_text(
                _first(record, "canonical_image_url", "image_url", "image", "img")
            )
            try:
                products.append(
                    CanonicalProduct(
                        product_id=product_id,
                        brand=brand,
                        name=name,
                        variants=tuple(variants),
                        canonical_image_url=image_url,
                    )
                )
            except ValueError as exc:
                skipped.append(f"record {index}: {exc}")

        if not products:
            detail = "; ".join(skipped[:5])
            raise CatalogFormatError(
                "Catalog was readable but no safe canonical products could be parsed. "
                + detail
            )

        return cls(products, source)

    def get(self, product_id: str) -> CanonicalProduct | None:
        """Return a product by its exact canonical ID."""
        return self._by_id.get(str(product_id))

    def all_products(self) -> tuple[CanonicalProduct, ...]:
        """Return all successfully parsed canonical products."""
        return self._products

    def product_count(self) -> int:
        return len(self._products)

    def skipped_variant_count(self) -> int:
        """Count is not available without retaining raw records; returns zero."""
        return 0

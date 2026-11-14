"""CJ Shopping XML adapter for NOTINO.fr.

This connector parses an already-exported CJ feed. It performs no live retailer
requests and does not write to the production database. Persistence is delegated
to the catalog/offer repository layer after matching and validation.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Optional
import re
import xml.etree.ElementTree as ET

from gtin import is_valid_gtin


@dataclass(frozen=True)
class NotinoOffer:
    store: str
    external_id: str
    title: str
    brand: str
    gtin: str
    price: Decimal
    currency: str
    availability: str
    affiliate_url: str
    image_url: str
    size: str
    gender: str
    product_type: str
    description: str
    captured_at: str
    item_group_id: str
    sale_price: Optional[Decimal] = None

    def to_dict(self) -> dict:
        """Return a JSON-friendly normalized offer payload."""
        result = asdict(self)
        result["price"] = str(self.price)
        result["sale_price"] = str(self.sale_price) if self.sale_price is not None else None
        return result


def _value(entry: ET.Element, name: str) -> str:
    node = entry.find(name)
    return (node.text or "").strip() if node is not None and node.text else ""


def _money(raw: str, *, required: bool = False):
    if not raw:
        if required:
            raise ValueError("missing price")
        return None, None
    match = re.fullmatch(r"\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Z]{3})\s*", raw)
    if not match:
        if required:
            raise ValueError(f"invalid money value: {raw!r}")
        return None, None
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {raw!r}") from exc
    if amount <= 0:
        raise ValueError("price must be greater than zero")
    return amount, match.group(2)


def _is_perfume(entry: ET.Element) -> bool:
    category_id = _value(entry, "google_product_category")
    category_name = _value(entry, "google_product_category_name").casefold()
    return category_id == "479" or "parfums et eaux de cologne" in category_name


def parse_entry(entry: ET.Element) -> Optional[NotinoOffer]:
    """Parse one feed entry; return None for non-perfume catalog items."""
    if not _is_perfume(entry):
        return None

    gtin = _value(entry, "gtin")
    if not is_valid_gtin(gtin):
        raise ValueError(f"invalid or missing GTIN/check digit for {_value(entry, 'id')!r}")

    price, currency = _money(_value(entry, "price"), required=True)
    sale_price, sale_currency = _money(_value(entry, "sale_price"))
    if sale_price is not None and sale_currency != currency:
        sale_price = None

    availability = _value(entry, "availability").casefold()
    if availability not in {"in stock", "out of stock", "preorder", "backorder"}:
        raise ValueError(f"unknown availability value: {availability!r}")

    affiliate_url = _value(entry, "link")
    if not affiliate_url.startswith(("https://", "http://")):
        raise ValueError("missing or invalid affiliate URL")

    return NotinoOffer(
        store="NOTINO.fr",
        external_id=_value(entry, "id"),
        title=_value(entry, "title"),
        brand=_value(entry, "brand"),
        gtin=gtin,
        price=price,
        currency=currency,
        availability=availability,
        affiliate_url=affiliate_url,
        image_url=_value(entry, "image_link"),
        size=_value(entry, "size"),
        gender=_value(entry, "gender"),
        product_type=_value(entry, "product_type"),
        description=_value(entry, "description"),
        captured_at=_value(entry, "last_updated"),
        item_group_id=_value(entry, "item_group_id"),
        sale_price=sale_price,
    )


def iter_notino_offers(feed_path: str | Path) -> Iterator[NotinoOffer]:
    """Stream validated perfume offers from a plain CJ XML feed."""
    for _, entry in ET.iterparse(str(feed_path), events=("end",)):
        if entry.tag.rsplit("}", 1)[-1] == "entry":
            try:
                offer = parse_entry(entry)
                if offer is not None:
                    yield offer
            finally:
                entry.clear()

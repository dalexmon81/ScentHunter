"""Refresh retailer-only CJ listings without inventing canonical matches."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import InvalidOperation
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import delete, insert, select

from app.models import NotinoFeedListing
from connectors.notino_cj import _money
from product_matcher import ProductMatcher
from scripts.build_notino_match_candidates import parse_size

_CJ_HOSTS = {
    "www.anrdoezrs.net", "www.dpbolvw.net", "www.jdoqocy.com",
    "www.kqzyfj.com", "www.tkqlhce.com",
}


def _affiliate_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        destinations = parse_qs(parsed.query).get("url", [])
        if (
            parsed.scheme != "https" or parsed.hostname not in _CJ_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not parsed.path.startswith("/click-") or len(destinations) != 1
        ):
            return False
        destination = urlsplit(destinations[0])
        return (
            destination.scheme == "https"
            and destination.hostname in {"notino.fr", "www.notino.fr"}
            and not destination.username and not destination.password
            and destination.port in (None, 443)
            and destination.path not in ("", "/")
        )
    except ValueError:
        return False


def refresh_notino_listings(session, rows: list[dict], captured_at: datetime) -> dict:
    """Replace the complete snapshot atomically; rejected rows are counted."""
    listings = []
    rejected = Counter()
    for row in rows:
        external_id = str(row.get("id") or "").strip()
        brand = str(row.get("brand") or "").strip()
        title = str(row.get("title") or "").strip()
        url = str(row.get("link") or "").strip()
        updated = str(row.get("last_updated") or "").strip()
        try:
            timestamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            valid_time = timestamp.tzinfo is not None and timestamp.utcoffset() is not None
        except ValueError:
            valid_time = False
        if not external_id or not brand or not title or not valid_time:
            rejected["missing_identity_or_timestamp"] += 1
            continue
        if ProductMatcher._is_non_fragrance_offer({"name": title, "brand": brand, "url": url}):
            rejected["non_fragrance"] += 1
            continue
        if not _affiliate_url(url):
            rejected["invalid_affiliate_url"] += 1
            continue
        availability = str(row.get("availability") or "").strip().casefold()
        if availability not in {"in stock", "out of stock"}:
            rejected["unknown_availability"] += 1
            continue
        try:
            price, currency = _money(str(row.get("price") or ""), required=True)
            sale, sale_currency = _money(str(row.get("sale_price") or ""))
        except (ValueError, InvalidOperation):
            rejected["invalid_price"] += 1
            continue
        if currency != "EUR":
            rejected["non_eur_price"] += 1
            continue
        if row.get("sale_price") and (
            sale is None or sale_currency != currency or sale > price
        ):
            rejected["invalid_sale_price"] += 1
            continue
        if sale is not None:
            price = sale
        image = str(row.get("image_link") or "").strip()
        try:
            if image and (urlsplit(image).scheme != "https" or not urlsplit(image).hostname):
                raise ValueError("invalid image URL")
        except ValueError:
            rejected["invalid_image_url"] += 1
            image = ""
        listings.append({
            "external_id": external_id, "brand": brand, "title": title,
            "gtin": str(row.get("gtin") or "").strip() or None,
            "size_ml": parse_size(row.get("size", "")) or parse_size(title),
            "price": price, "currency": currency,
            "availability": availability, "affiliate_url": url,
            "image_url": image or None, "source_last_updated": updated,
            "captured_at": captured_at,
        })
    if not listings:
        raise ValueError("notino_feed_snapshot_has_no_valid_listings")
    previous = dict(session.execute(select(
        NotinoFeedListing.external_id, NotinoFeedListing.source_last_updated,
    )).all())
    for listing in listings:
        old = previous.get(listing["external_id"])
        if old:
            current_time = datetime.fromisoformat(listing["source_last_updated"].replace("Z", "+00:00"))
            previous_time = datetime.fromisoformat(old.replace("Z", "+00:00"))
            if current_time < previous_time:
                raise ValueError(f"notino_feed_snapshot_older:{listing['external_id']}")
    session.execute(delete(NotinoFeedListing))
    session.execute(insert(NotinoFeedListing), listings)
    return {"listings": len(listings), "rejected": dict(rejected)}

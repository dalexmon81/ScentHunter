"""Read-only search of canonical variants and previously promoted offers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, IngestionRaw, MatchAudit, Offer, ProductVariant, Store


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _display_fragrance_name(name: str, concentration: str | None) -> str:
    """Avoid repeating a concentration already embedded in the fragrance name."""
    display = " ".join((name or "").split())
    suffix = " ".join((concentration or "").split())
    if suffix and display.casefold().endswith(suffix.casefold()):
        base = display[: -len(suffix)].rstrip(" -–—").strip()
        if base:
            return base
    return display


def _offer_url_valid(url: str, domain: str | None) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = (domain or "").lower().rstrip(".")
        return (
            parsed.scheme in {"http", "https"} and bool(allowed)
            and (host == allowed or host.endswith("." + allowed))
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 80, 443)
        )
    except ValueError:
        return False


def _display_offer_url(offer: Offer, store: Store, raw: IngestionRaw) -> str:
    """Return the retailer product URL; catalog search never emits affiliate redirects."""
    return offer.url


def _notino_source_timestamp(raw: IngestionRaw) -> datetime | None:
    payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
    value = payload.get("source_updated_at")
    observation = payload.get("refresh_observation")
    if not value and isinstance(observation, dict):
        value = observation.get("source_updated_at")
    if not value:
        xml = payload.get("raw_xml")
        if not xml and isinstance(observation, dict):
            xml = observation.get("raw_xml")
        match = re.search(r"<last_updated>\s*([^<]+?)\s*</last_updated>", str(xml or ""), re.I)
        value = match.group(1) if match else None
    # Direct storefront captures have no retailer feed timestamp. Accept only
    # their own persisted capture timestamp; never substitute download time for
    # legacy CJ/VIV records, whose source freshness must remain independently proven.
    if not value and payload.get("source") == "notino_public_storefront":
        value = payload.get("captured_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _eligible_offer_rows(session: Session, now: datetime, variant_ids: list | None = None):
    audit_exists = exists(select(MatchAudit.id).where(
        MatchAudit.offer_id == Offer.id,
        MatchAudit.product_variant_id == Offer.product_variant_id,
    ))
    statement = (
        select(Offer, Store, IngestionRaw)
        .join(Store, Offer.store_id == Store.id)
        .join(IngestionRaw, Offer.ingestion_raw_id == IngestionRaw.id)
        .where(
            Offer.status == "active",
            Store.status == "active",
            IngestionRaw.status == "promoted",
            IngestionRaw.product_variant_id == Offer.product_variant_id,
            IngestionRaw.store_id == Offer.store_id,
            Offer.availability.in_(("in_stock", "out_of_stock")),
            Offer.price > 0,
            Offer.currency == "EUR",
            Offer.captured_at >= now - timedelta(hours=24),
            Offer.captured_at <= now,
            or_(Offer.valid_until.is_(None), Offer.valid_until > now),
            audit_exists,
        )
    )
    if variant_ids is not None:
        if not variant_ids:
            return []
        statement = statement.where(Offer.product_variant_id.in_(variant_ids))
    rows = session.execute(statement.order_by(Offer.price, Offer.id)).all()
    eligible = []
    for offer, store, raw in rows:
        if raw.raw_payload.get("currency_explicit") is not True:
            continue
        if not _offer_url_valid(offer.url, store.domain):
            continue
        if store.slug == "notino-fr":
            # Only records captured by the approved direct storefront connector
            # may be published. Historical CJ/VIV rows remain quarantined.
            if raw.raw_payload.get("source") != "notino_public_storefront":
                continue
            source_time = _notino_source_timestamp(raw)
            if source_time is None or source_time > now + timedelta(minutes=5):
                continue
            if source_time < now - timedelta(hours=12):
                continue
        eligible.append((offer, store, raw))
    return eligible


def search_catalog(session: Session, query: str, *, now: datetime | None = None) -> dict:
    """Search the database only; never contact a retailer or mutate catalog data."""
    now = _utc(now or datetime.now(timezone.utc))
    tokens = re.findall(r"[^\W\d_]+|\d+", query.casefold(), flags=re.UNICODE)
    if not tokens or all(token == "ml" for token in tokens):
        return {"query": query, "count": 0, "offer_count": 0, "results": [], "status": "completed", "completed": True}

    text_fields = (Brand.name, Fragrance.name, ProductVariant.concentration)
    statement = select(ProductVariant, Fragrance, Brand).join(
        Fragrance, ProductVariant.fragrance_id == Fragrance.id
    ).join(Brand, Fragrance.brand_id == Brand.id)
    # Treat explicit variant attributes as hard filters, but do not let
    # incidental words ("spray", "vapourisateur", "parfum", etc.) erase an
    # otherwise valid product result. A text token is a required term only
    # when that token exists somewhere in the canonical catalog.
    ignored_tokens = {"ml", "eau", "spray", "vap", "vaporisateur"}
    for token in tokens:
        if token in ignored_tokens:
            continue
        if token.isdecimal():
            if len(token) > 5 or int(token) > 10000:
                return {"query": query, "count": 0, "offer_count": 0, "results": [], "status": "completed", "completed": True}
            statement = statement.where(ProductVariant.size_ml == int(token))
        elif token in {"edp", "edt"}:
            concentration = "eau de parfum" if token == "edp" else "eau de toilette"
            statement = statement.where(or_(
                func.lower(ProductVariant.concentration).contains(concentration, autoescape=True),
                func.lower(ProductVariant.concentration) == token,
            ))
        elif token in {"tester", "refill", "gift", "set", "mini", "miniature"}:
            flag = (
                ProductVariant.is_tester if token == "tester" else
                ProductVariant.is_refill if token == "refill" else
                ProductVariant.is_gift_set if token in {"gift", "set"} else
                ProductVariant.is_mini
            )
            statement = statement.where(flag.is_(True))
        else:
            token_condition = or_(*(
                func.lower(field).contains(token, autoescape=True) for field in text_fields
            ))
            token_exists = session.scalar(select(exists(
                select(1).select_from(Brand)
                .join(Fragrance, Fragrance.brand_id == Brand.id)
                .join(ProductVariant, ProductVariant.fragrance_id == Fragrance.id)
                .where(token_condition)
            )))
            # Ignore incidental words not represented in the catalog; keep
            # every recognized brand/name token as a required search term.
            if token_exists:
                statement = statement.where(token_condition)
    rows = session.execute(statement.order_by(Brand.name, Fragrance.name, ProductVariant.size_ml, ProductVariant.id)).all()
    # Canonical fragrance identities are searchable even when no commercial
    # variant has been declared yet. This is essential for catalog-first
    # discovery: retailer coverage must never determine catalog membership.
    identity_statement = select(Fragrance, Brand).join(
        Brand, Fragrance.brand_id == Brand.id
    )
    identity_ignored = {"ml", "eau", "spray", "vap", "vaporisateur"}
    for token in tokens:
        if token in identity_ignored or token.isdecimal() or token in {
            "edp", "edt", "tester", "refill", "gift", "set", "mini", "miniature"
        }:
            continue
        identity_condition = or_(
            func.lower(Brand.name).contains(token, autoescape=True),
            func.lower(Fragrance.name).contains(token, autoescape=True),
        )
        identity_exists = session.scalar(select(exists(
            select(1).select_from(Brand)
            .join(Fragrance, Fragrance.brand_id == Brand.id)
            .where(identity_condition)
        )))
        if identity_exists:
            identity_statement = identity_statement.where(identity_condition)
    # Identity-only rows cannot satisfy explicit commercial variant selectors
    # (size, concentration, tester/refill/set/mini). Keep those searches strict.
    has_variant_selector = any(
        token.isdecimal() or token in {"edp", "edt", "tester", "refill", "gift", "set", "mini", "miniature"}
        for token in tokens
    )
    identity_rows = [] if has_variant_selector else session.execute(
        identity_statement.order_by(Brand.name, Fragrance.name)
    ).all()
    represented_fragrance_ids = {fragrance.id for _, fragrance, _ in rows}
    identities_without_variants = [
        (fragrance, brand) for fragrance, brand in identity_rows
        if fragrance.id not in represented_fragrance_ids
        and not session.scalar(select(exists(
            select(1).select_from(ProductVariant)
            .where(ProductVariant.fragrance_id == fragrance.id)
        )))
    ]

    variant_ids = [variant.id for variant, _, _ in rows]
    sizes = {variant.id: variant.size_ml for variant, _, _ in rows}
    offers_by_variant: dict = {}
    for offer, store, raw in _eligible_offer_rows(session, now, variant_ids):
        offers_by_variant.setdefault(offer.product_variant_id, []).append({
            "store": store.name,
            "url": _display_offer_url(offer, store, raw),
            "product_url": offer.url,
            "price": str(offer.price),
            "currency": offer.currency,
            "availability": offer.availability,
            "size_ml": sizes[offer.product_variant_id],
            "variant_id": str(offer.product_variant_id),
            "captured_at": _utc(offer.captured_at).isoformat(),
            "shipping_cost": str(offer.shipping_cost) if offer.shipping_cost is not None else None,
        })

    # One public result represents one fragrance + concentration + packaging
    # identity. The commercial sizes remain nested formats, never separate
    # top-level perfume cards. This is the response contract already consumed
    # by the frontend's product -> format -> retailer-offer navigation.
    grouped: dict[tuple, dict] = {}
    for variant, fragrance, brand in rows:
        concentration = " ".join((variant.concentration or "").casefold().split())
        flags = (
            variant.is_tester, variant.is_refill,
            variant.is_gift_set, variant.is_mini,
        )
        key = (fragrance.id, concentration, *flags)
        group = grouped.get(key)
        if group is None:
            suffix = "|".join((concentration or "unspecified", *(
                "u" if flag is None else ("1" if flag else "0") for flag in flags
            )))
            group = {
                "catalog_id": str(variant.id),
                "concentration_group_key": suffix,
                "brand": brand.name,
                "name": " ".join(filter(None, (
                    _display_fragrance_name(fragrance.name, variant.concentration),
                    variant.concentration,
                    "Tester" if variant.is_tester is True else None,
                    "Refill" if variant.is_refill is True else None,
                    "Gift set" if variant.is_gift_set is True else None,
                    "Mini" if variant.is_mini is True else None,
                ))),
                "image": fragrance.image_url,
                "formats": [],
                "variant_ids": [],
                "offers": [],
            }
            grouped[key] = group

        variant_id = str(variant.id)
        group["variant_ids"].append(variant_id)
        if variant.size_ml is not None:
            if not any(item["size_ml"] == variant.size_ml for item in group["formats"]):
                group["formats"].append({
                    "size_ml": variant.size_ml,
                    "variant_id": variant_id,
                })
        group["offers"].extend(offers_by_variant.get(variant.id, []))

    results = list(grouped.values())
    # Public search is a shopping surface: never show catalog-only products
    # or bottle sizes unless at least one currently verified offer exists.
    # Canonical variants remain stored in PostgreSQL and become visible as soon
    # as a fresh, validated retailer offer is promoted.
    visible_results = []
    for group in results:
        verified_sizes = {
            offer.get("size_ml") for offer in group["offers"]
            if offer.get("size_ml") is not None
        }
        group["formats"] = [
            item for item in group["formats"]
            if item.get("size_ml") in verified_sizes
        ]
        if not group["offers"] or not group["formats"]:
            continue
        group["formats"].sort(key=lambda item: item["size_ml"])
        group["offers"].sort(key=lambda item: (
            item.get("size_ml") is None,
            item.get("size_ml") or 0,
            float(item["price"]),
            item.get("store") or "",
        ))
        visible_results.append(group)

    # Identity-only catalog entries are intentionally not public search hits.
    # They remain in the canonical database for future matching and ingestion.
    results = visible_results
    results.sort(key=lambda item: (item["brand"].casefold(), item["name"].casefold()))

    return {
        "query": query, "count": len(results),
        "offer_count": sum(len(result["offers"]) for result in results),
        "results": results, "status": "completed", "completed": True,
    }


def catalog_status(session: Session, *, now: datetime | None = None) -> dict:
    """Return read-only operational counts using the exact public-offer gate."""
    now = _utc(now or datetime.now(timezone.utc))
    stores = session.scalars(select(Store).order_by(Store.slug)).all()
    active_stores = [store for store in stores if store.status == "active"]
    eligible = _eligible_offer_rows(session, now)
    offers_by_store = {store.slug: 0 for store in active_stores}
    latest_by_store = {}
    for offer, store, _raw in eligible:
        offers_by_store[store.slug] = offers_by_store.get(store.slug, 0) + 1
        captured_at = _utc(offer.captured_at)
        previous = latest_by_store.get(store.slug)
        if previous is None or captured_at > previous:
            latest_by_store[store.slug] = captured_at
    active_offer_count = session.scalar(
        select(func.count()).select_from(Offer).where(Offer.status == "active")
    ) or 0
    unresolved_count = session.scalar(
        select(func.count()).select_from(IngestionRaw).where(
            IngestionRaw.status.in_(("pending", "unmatched"))
        )
    ) or 0
    return {
        "status": "ready",
        "canonical_products": session.scalar(select(func.count()).select_from(Fragrance)) or 0,
        "canonical_variants": session.scalar(select(func.count()).select_from(ProductVariant)) or 0,
        "active_stores": len(active_stores),
        "published_offers": len(eligible),
        "offers_by_store": offers_by_store,
        "latest_offer_update_by_store": {
            slug: value.isoformat() for slug, value in latest_by_store.items()
        },
        "active_offers_not_currently_publishable": max(0, active_offer_count - len(eligible)),
        "unresolved_match_reviews": unresolved_count,
        "freshness_window_hours": 24,
    }
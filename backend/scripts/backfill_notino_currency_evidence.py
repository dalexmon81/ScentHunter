"""Backfill explicit Notino currency evidence from preserved original CJ XML.

Only metadata is updated. Offers, prices, stock, URLs and canonical matches are
never changed. Rows without independently verifiable EUR evidence are skipped.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import xml.etree.ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import IngestionRaw, Offer, Store
from scrapers.notino.affiliate_feed import _parse_item


def _raw_xml(payload: dict) -> str | None:
    value = payload.get("raw_xml")
    if not value and isinstance(payload.get("refresh_observation"), dict):
        value = payload["refresh_observation"].get("raw_xml")
    return value if isinstance(value, str) and value.strip() else None


def _has_matching_currency_evidence(offer: Offer, raw: IngestionRaw) -> bool:
    xml = _raw_xml(raw.raw_payload or {})
    if not xml:
        return False
    try:
        item = _parse_item(ET.fromstring(xml))
    except (ET.ParseError, TypeError, ValueError):
        return False
    if item is None or item.currency != "EUR":
        return False
    if item.external_id != offer.external_product_id:
        return False
    if item.url != offer.url:
        return False
    try:
        if Decimal(str(item.price)) != Decimal(str(offer.price)):
            return False
    except (InvalidOperation, TypeError, ValueError):
        return False
    return item.availability == offer.availability


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="persist only independently verified currency evidence")
    args = parser.parse_args()
    engine = make_engine()
    counts = {"checked": 0, "already_explicit": 0, "verified_candidates": 0,
              "updated": 0, "skipped_no_evidence": 0}
    try:
        with Session(engine) as session, session.begin():
            rows = session.execute(
                select(Offer, Store, IngestionRaw)
                .join(Store, Offer.store_id == Store.id)
                .join(IngestionRaw, Offer.ingestion_raw_id == IngestionRaw.id)
                .where(Offer.status == "active", Store.slug == "notino-fr")
            ).all()
            for offer, _store, raw in rows:
                counts["checked"] += 1
                payload = dict(raw.raw_payload or {})
                if payload.get("currency_explicit") is True:
                    counts["already_explicit"] += 1
                    continue
                if not _has_matching_currency_evidence(offer, raw):
                    counts["skipped_no_evidence"] += 1
                    continue
                counts["verified_candidates"] += 1
                if args.apply:
                    payload["currency_explicit"] = True
                    payload["currency_evidence_backfill"] = (
                        "reparsed_preserved_cj_xml_exact_offer_identity_price_stock_eur"
                    )
                    raw.raw_payload = payload
                    counts["updated"] += 1
        print(json.dumps({
            "mode": "apply" if args.apply else "dry_run",
            **counts,
        }, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

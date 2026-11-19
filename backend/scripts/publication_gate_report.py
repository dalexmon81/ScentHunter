"""Read-only breakdown of active offers rejected by the public catalog gate."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import IngestionRaw, MatchAudit, Offer, Store
from app.search.catalog import _offer_url_valid, _utc


def main() -> int:
    now = datetime.now(timezone.utc)
    engine = make_engine()
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(Offer, Store, IngestionRaw)
                .join(Store, Offer.store_id == Store.id)
                .join(IngestionRaw, Offer.ingestion_raw_id == IngestionRaw.id)
                .where(Offer.status == "active")
            ).all()
            audit_pairs = {
                (audit.offer_id, audit.product_variant_id)
                for audit in session.scalars(select(MatchAudit)).all()
            }
            totals = Counter()
            by_store: dict[str, Counter] = {}
            for offer, store, raw in rows:
                failures = []
                if store.status != "active":
                    failures.append("store_not_active")
                if raw.status != "promoted":
                    failures.append("raw_not_promoted")
                if raw.product_variant_id != offer.product_variant_id:
                    failures.append("raw_variant_mismatch")
                if raw.store_id != offer.store_id:
                    failures.append("raw_store_mismatch")
                if offer.availability != "in_stock":
                    failures.append("not_in_stock")
                if offer.price is None or offer.price <= 0:
                    failures.append("invalid_price")
                if offer.currency != "EUR":
                    failures.append("currency_not_eur")
                captured = _utc(offer.captured_at)
                if captured < now - timedelta(hours=24):
                    failures.append("older_than_24h")
                if captured > now:
                    failures.append("captured_in_future")
                if offer.valid_until is not None and _utc(offer.valid_until) <= now:
                    failures.append("expired")
                if (offer.id, offer.product_variant_id) not in audit_pairs:
                    failures.append("missing_match_audit")
                if raw.raw_payload.get("currency_explicit") is not True:
                    failures.append("currency_not_explicit")
                if not _offer_url_valid(offer.url, store.domain):
                    failures.append("invalid_store_url")
                bucket = by_store.setdefault(store.slug, Counter())
                if not failures:
                    totals["eligible"] += 1
                    bucket["eligible"] += 1
                else:
                    totals["not_publishable"] += 1
                    bucket["not_publishable"] += 1
                    for reason in failures:
                        totals[reason] += 1
                        bucket[reason] += 1

            print("PUBLICATION_GATE_ACTIVE_OFFERS=" + str(len(rows)))
            print("PUBLICATION_GATE_ELIGIBLE=" + str(totals["eligible"]))
            print("PUBLICATION_GATE_NOT_PUBLISHABLE=" + str(totals["not_publishable"]))
            print("PUBLICATION_GATE_FAILURE_REASONS=" + str({
                key: value for key, value in sorted(totals.items())
                if key not in {"eligible", "not_publishable"}
            }))
            print("PUBLICATION_GATE_BY_STORE=" + str({
                slug: dict(sorted(counts.items()))
                for slug, counts in sorted(by_store.items())
            }))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

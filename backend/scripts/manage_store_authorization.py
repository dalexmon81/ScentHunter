#!/usr/bin/env python3
"""Operator-only management of written retailer authorization records.

This is deliberately a local CLI, not an HTTP/admin endpoint. Mutating
commands require PostgreSQL and an explicit confirmation environment value.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import database_url, make_engine
from app.models import Store, StoreAuthorization

CONFIRM_ENV = "SCENTHUNTER_OPERATOR_CONFIRM"
CONFIRM_VALUE = "I_VERIFIED_WRITTEN_RETAILER_CONSENT"
ALLOWED_SCOPES = {"product_discovery", "offer_data", "price_stock", "single_product_fetch"}
ALLOWED_METHODS = {"api", "feed", "affiliate_feed", "manual_url", "other"}


def parse_scopes(values: list[str]) -> list[str]:
    scopes = sorted({value.strip() for value in values if value.strip()})
    if not scopes:
        raise ValueError("at_least_one_authorization_scope_required")
    unknown = set(scopes) - ALLOWED_SCOPES
    if unknown:
        raise ValueError("unsupported_authorization_scope:" + ",".join(sorted(unknown)))
    if "price_stock" in scopes and "offer_data" not in scopes:
        raise ValueError("price_stock_scope_requires_offer_data_scope")
    if "product_discovery" in scopes and "offer_data" not in scopes:
        raise ValueError("product_discovery_scope_requires_offer_data_scope")
    return scopes


def parse_aware_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_must_include_timezone_offset")
    return parsed.astimezone(timezone.utc)


def validate_evidence_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("evidence_url_must_be_https")
    return value.strip()


def _require_operator_confirmation() -> None:
    if os.environ.get(CONFIRM_ENV) != CONFIRM_VALUE:
        raise RuntimeError(
            f"Set {CONFIRM_ENV}={CONFIRM_VALUE} only after personally verifying "
            "the retailer's written permission and its exact scope."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List recorded authorization grants (read-only).")

    approve = sub.add_parser("approve", help="Record verified written retailer consent.")
    approve.add_argument("--store", required=True, help="Exact store slug from the stores table.")
    approve.add_argument("--method", required=True, choices=sorted(ALLOWED_METHODS))
    approve.add_argument("--scope", required=True, action="append", dest="scopes")
    approve.add_argument("--reference", required=True, help="Exact ticket, contract or consent reference.")
    approve.add_argument("--evidence-url", required=True, help="HTTPS URL to the retained permission evidence.")
    approve.add_argument("--approved-by", required=True, help="Operator identity for the audit record.")
    approve.add_argument("--valid-from", help="ISO-8601 timestamp with timezone; defaults to now.")
    approve.add_argument("--expires-at", help="Optional ISO-8601 timestamp with timezone.")
    approve.add_argument("--terms-json", default="{}", help="JSON object recording agreed conditions.")
    approve.add_argument("--notes", default="")

    revoke = sub.add_parser("revoke", help="Revoke a grant without deleting its audit history.")
    revoke.add_argument("--store", required=True)
    revoke.add_argument("--authorization-id", required=True, help="UUID of the exact grant to revoke.")
    revoke.add_argument("--notes", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = make_engine()
    try:
        backend = make_url(database_url()).get_backend_name()
        if args.command != "list":
            if backend != "postgresql":
                raise RuntimeError("authorization_mutations_require_postgresql")
            _require_operator_confirmation()

        with Session(engine) as session:
            if args.command == "list":
                rows = session.execute(
                    select(Store.slug, StoreAuthorization)
                    .join(StoreAuthorization, StoreAuthorization.store_id == Store.id)
                    .order_by(Store.slug, StoreAuthorization.created_at.desc())
                ).all()
                for slug, grant in rows:
                    print(json.dumps({
                        "store": slug, "id": str(grant.id), "status": grant.status,
                        "method": grant.collection_method, "scopes": grant.scopes,
                        "reference": grant.authorization_reference,
                        "approved_by": grant.approved_by,
                        "approved_at": grant.approved_at.isoformat() if grant.approved_at else None,
                        "valid_from": grant.valid_from.isoformat() if grant.valid_from else None,
                        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
                        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
                        "evidence_url": grant.evidence_url,
                    }, sort_keys=True))
                return 0

            store = session.scalar(select(Store).where(Store.slug == args.store))
            if store is None:
                raise ValueError("store_not_found:" + args.store)

            if args.command == "approve":
                scopes = parse_scopes(args.scopes)
                evidence_url = validate_evidence_url(args.evidence_url)
                valid_from = parse_aware_datetime(args.valid_from) or datetime.now(timezone.utc)
                expires_at = parse_aware_datetime(args.expires_at)
                if expires_at is not None and expires_at <= valid_from:
                    raise ValueError("expires_at_must_be_after_valid_from")
                terms = json.loads(args.terms_json)
                if not isinstance(terms, dict):
                    raise ValueError("terms_json_must_be_an_object")
                reference = args.reference.strip()
                approved_by = args.approved_by.strip()
                if not reference or not approved_by:
                    raise ValueError("authorization_reference_and_approver_required")
                grant = StoreAuthorization(
                    store_id=store.id, status="approved",
                    collection_method=args.method, scopes=scopes,
                    authorization_reference=reference, evidence_url=evidence_url,
                    approved_by=approved_by, approved_at=datetime.now(timezone.utc),
                    valid_from=valid_from, expires_at=expires_at,
                    terms=terms, notes=args.notes.strip() or None,
                )
                session.add(grant)
                session.commit()
                print(json.dumps({"created": True, "store": store.slug, "authorization_id": str(grant.id), "scopes": scopes}))
                return 0

            if args.command == "revoke":
                grant_id = UUID(args.authorization_id)
                grant = session.scalar(
                    select(StoreAuthorization).where(
                        StoreAuthorization.id == grant_id,
                        StoreAuthorization.store_id == store.id,
                    )
                )
                if grant is None:
                    raise ValueError("authorization_not_found_for_store")
                if grant.status != "approved" or grant.revoked_at is not None:
                    raise ValueError("only_an_active_approved_grant_can_be_revoked")
                grant.status = "revoked"
                grant.revoked_at = datetime.now(timezone.utc)
                if args.notes.strip():
                    grant.notes = (grant.notes + "\n" if grant.notes else "") + "Revocation: " + args.notes.strip()
                session.commit()
                print(json.dumps({"revoked": True, "store": store.slug, "authorization_id": str(grant.id)}))
                return 0
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

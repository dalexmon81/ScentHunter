# Phase 6 — validation and publication lifecycle

## Implemented on `phase6/matching-validation`

The lifecycle is now represented by separate fields. Existing queue and legacy
publication columns remain unchanged for compatibility.

- `IngestionRaw.status`: legacy queue state
  (`pending | unmatched | matched | promoted | rejected`).
- `IngestionRaw.validation_status`: `pending | validated | rejected`.
- `Offer.status`: legacy field; successful offers still use `active`.
- `Offer.publication_status`: `draft | published | stale | rejected | quarantined`.

The SQLAlchemy model includes check constraints for both new lifecycle fields.
Alembic revision `0008_offer_lifecycle_states` adds the columns, constraints,
and publication-status index. The migration has **not** been applied to any
database.

## Enforced publication gate

The validation worker records its result independently of the queue state.
The promotion service refuses to publish unless validation is `validated`.
It also requires a resolved canonical variant, active store, positive price,
valid ISO 4217 currency, absolute HTTPS URL, explicit `in_stock`, fresh
timezone-aware capture, and match confidence of at least 0.950. Successful
creation or refresh sets legacy `Offer.status=active` and
`publication_status=published`.

Semantic matching is opt-in through an injected embedding provider. Without a
configured provider it does not make semantic matches. Ambiguous or structurally
inconsistent identity remains unresolved for review.

## Compatibility and data migration risks

Existing offers receive the new default `publication_status=draft` when
revision 0008 is applied. Their legacy `status=active` is preserved, but any
new reader filtering on `publication_status=published` will exclude them
until their evidence is revalidated. Do not mass-backfill them to published
without checking their evidence.

Existing matched raw rows receive `validation_status=pending` and will be
blocked at promotion until the validation worker is rerun successfully.
This is deliberate fail-closed behavior.

## Required verification before rollout

1. Run the complete backend unit/regression suite on this branch.
2. Test migration upgrade and downgrade against an explicitly verified,
   isolated staging database.
3. Verify existing-row counts and legacy readers before enabling any new
   publication-status filter.
4. Revalidate eligible historical offers; keep uncertain rows in draft or
   review.
5. Verify promotion retry behavior and ensure no duplicate Offer or
   PriceHistory records.
6. Keep Beat, live scraping, and production deployment disabled until reviewed.

## Safety

No migration is run by this branch's code changes. Never point the migration
at production. Deploy and schema rollout require separate review after tests.

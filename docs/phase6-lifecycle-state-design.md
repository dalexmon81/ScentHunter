# Phase 6 — validation and publication lifecycle state design

## Scope and safety

This document records the proposed lifecycle model for review. It does not alter
SQLAlchemy models, create an Alembic migration, or change any database. Apply a
schema migration only after the state transitions and backfill have been tested
against an isolated staging database identity.

## Existing constraints that must be preserved

- `ingestion_raw.status` is constrained to
  `pending | unmatched | matched | promoted | rejected`.
- Matching and promotion workers query those existing values.
- `offer.status` is a legacy publication field currently using `active`.
- `canonical_identity_reviews.status` is a separate review workflow:
  `pending | approved | rejected | duplicate`.
- Connector quarantine and dead-letter handling are store/task operational
  states, not canonical product-match states.

Do not overload any of these existing columns with new lifecycle values.

## Proposed separation

### Ingestion evidence

Keep `IngestionRaw.status` as the compatibility/work-queue state used by the
current workers. Add a separate `validation_status` only if the application
needs a durable queryable validation result independent of worker queue state.

Suggested values:
- `pending`
- `validated`
- `rejected`

Store machine-readable validation reasons separately (JSON array or related
validation event rows); do not replace `rejection_reason` until all consumers
are migrated.

### Published offer

Add a separate `publication_status` to Offer, rather than changing legacy
`Offer.status`.

Suggested values:
- `draft` — offer row exists but is not visible to search
- `published` — passed all publication gates
- `stale` — evidence exceeded the freshness policy
- `rejected` — failed a permanent publication rule
- `quarantined` — held for operator review; not searchable

The search API must filter explicitly on `publication_status = published`
after a compatibility rollout. Until then, preserve current `status=active`
semantics for existing production consumers.

### Connector operations

Keep connector health/quarantine in store/connector operational metadata and
dead-letter records. Do not label every raw product record as quarantined merely
because its connector is temporarily unhealthy.

## Required transition rules

1. Raw evidence is immutable/auditable; refresh observations append evidence.
2. Validation is idempotent and records all rejection reasons.
3. Matching can only assign a canonical variant on deterministic evidence or a
   future explicitly configured semantic provider above a conservative threshold.
4. Ambiguous identity always enters human review; it never reaches promotion.
5. Promotion requires validated evidence, active store, exact resolved variant,
   valid ISO 4217 currency, positive price, HTTPS URL, explicit in-stock state,
   fresh timezone-aware capture, and confidence >= 0.950.
6. Search exposes only published offers; stale/rejected/quarantined offers are
   excluded regardless of legacy active status.

## Migration plan (not yet authorized or implemented)

1. Add nullable publication/validation columns with safe defaults.
2. Backfill existing active offers to published only after checking their
   evidence; otherwise mark them draft for revalidation.
3. Deploy readers that understand both legacy and new fields.
4. Switch search filtering to publication status after backfill verification.
5. Make the new fields non-null only after all writers populate them.
6. Retain legacy status until all consumers have been migrated and measured.

## Acceptance tests before migration

- Legacy ingestion status constraint remains unchanged.
- Old worker queries still select pending/unmatched/matched rows correctly.
- Existing active offers remain visible during compatibility rollout.
- Draft, stale, rejected, and quarantined offers never appear in search.
- Failed validation cannot be promoted by a direct task invocation.
- Repeated validation/promotion is idempotent and does not duplicate offers.
- Migration upgrade and downgrade are tested on an isolated staging database.

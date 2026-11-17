# Catalog-first search pilot

This is an isolated pilot, not a production cutover. `/api/catalog/search?q=...`
reads the Phase 2 canonical database configured by
`SCENTHUNTER_CATALOG_DATABASE_URL` (or `SCENTHUNTER_DATABASE_URL`). It does
not query stores, use Meilisearch, or change the legacy search. The existing
Bplatz background hydration can mirror records to this database when
`BPLATZ_PHASE2_PERSISTENCE=1`; the canonical schema, seed, active Bplatz store,
and background worker must already be configured. See the PostgreSQL migration
plan before changing the production database or enabling the mirror.

Open the frontend with `?catalog_first=1` to opt into the pilot. Other users
continue to use the existing search. Search for `French Avenue Liquid Brun
EDP 100ml`; the 150 ml Limited Edition is a separate canonical variant.
An identified variant can be shown without an offer.

Only active EUR offers with an explicit `in_stock` signal, a positive price, an
HTTP(S) URL on the configured store domain, an explicitly sourced currency, a promoted raw record, a matching
audit, and an active store are returned. The observation must be at most 24
hours old, not in the future, and not past `valid_until`. This conservative
24-hour pilot limit is not a measured freshness SLA. Unknown shipping costs
are shown as unknown. Results are ordered by product price, not total cost.
No numeric confidence threshold is asserted: the current Bplatz matcher
records a match method but does not supply a calibrated confidence score.

The saved Bplatz HTML fixture is historical and is used only in tests; it is
not a current offer. Actual offers depend on successful background hydration.
The pilot does not provide typo tolerance, an index, calibrated ranking, or
automated availability guarantees. Validate freshness, match precision,
coverage, permissions, operational rollback, and real PostgreSQL deployment
before routing production traffic to it.

Existing promoted rows without currency provenance are excluded until a
successful new hydration records explicit structured currency. A default EUR
in the legacy parser is not evidence of currency.

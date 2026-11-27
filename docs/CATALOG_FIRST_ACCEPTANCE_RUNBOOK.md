# Catalog-first production acceptance runbook

This runbook defines the remaining database-backed acceptance checks. It is a checklist, not an execution record. Do not mark a gate passed until evidence is attached to the corresponding run.

## Safety preflight

- [ ] Confirm a current PostgreSQL backup and a tested restore point.
- [ ] Confirm the target database, app and worker environment; never point a smoke test at an unintended production database.
- [ ] Confirm migrations are at head and catalog seed verification passes.
- [ ] Confirm the six approved stores are present and active: Bplatz, Deloox BE, Sabina ES, Easycosmetic DE, Parfumzentrum DE and Notino FR.
- [ ] Confirm unapproved stores are absent from production scheduling.
- [ ] Confirm PostgreSQL is the only production queue backend and exactly one intended worker is claiming jobs.
- [ ] Confirm no CJ/VIV feed writer, credentials, feed URL or affiliate redirect is enabled in the production Notino path.
- [ ] Record baseline counts for canonical variants, active stores, offers by store, pending/unmatched raw records, queue jobs and price-history rows.

## Store ingestion acceptance

Run a bounded discovery for each approved store using a small, fixed set of known fragrance queries. Preserve the exact query, timestamp, run ID and raw evidence.

For every discovered product:
- [ ] Product URL belongs to the expected retailer domain and resolves to the same product URL after fetch.
- [ ] Product is a fragrance, not skincare, deodorant, gift set, tester, refill or mini unless that exact format is intentionally represented as a canonical variant.
- [ ] Brand, fragrance name, concentration and size are explicit and internally consistent.
- [ ] Price is positive and belongs to the sellable product, not a unit price, delivery fee, crossed-out price or search-card teaser.
- [ ] Currency is explicitly evidenced by the retailer.
- [ ] Availability is explicitly in stock or out of stock; unknown is not publishable.
- [ ] GTIN/SKU and product URL are retained when present.
- [ ] Canonical matching resolves to one exact variant. Ambiguous or unsupported formats remain pending.
- [ ] A successful record creates/updates one promoted ingestion row, one active offer and one matching audit, with no duplicate offer.
- [ ] Public search returns the offer only after all publication gates pass.

Do not infer multi-brand discovery from one known product URL. Deloox and Notino require a fresh live discovery pass across multiple independent brands before acceptance.

## Refresh acceptance

- [ ] Confirm the scheduler enqueues eligible active offers at the configured cadence.
- [ ] Confirm refresh jobs use the stable retailer product identity (URL where required).
- [ ] Complete one successful refresh per approved store and verify price, currency, availability, URL and source evidence.
- [ ] Verify the canonical product-variant ID is unchanged by refresh.
- [ ] Verify one price-history observation is appended and raw refresh evidence is retained.
- [ ] Verify missing price, missing/ambiguous stock, missing explicit currency, invalid URL, currency change and stale/future timestamps fail closed.
- [ ] Verify retryable errors are retried, permanent errors terminate, and stale worker leases are recovered without duplicate publication.
- [ ] Verify a failed refresh does not make an old offer appear freshly updated.

The scheduler interval is a queueing cadence, not a freshness guarantee.

## Catalog-first search acceptance

- [ ] Search known products and verify results are read from PostgreSQL canonical variants and promoted offers only.
- [ ] Instrument/block outbound retailer HTTP during the search request and verify the search succeeds without contacting any store.
- [ ] Verify inactive stores, inactive offers, unmatched/unpromoted raw rows, ambiguous matches, invalid URLs, non-EUR offers, missing explicit currency, unknown stock, zero/negative prices and expired/stale observations are excluded.
- [ ] Verify current in-stock and explicitly out-of-stock offers can be displayed with the correct state.
- [ ] Verify Notino results are sourced only from direct storefront captures and link directly to the Notino product page; historical CJ/VIV rows and affiliate redirects are never returned.
- [ ] Verify an unknown product returns no fabricated product or offer.

## Evidence and exit criteria

For each store, retain:
- discovery workflow URL and run ID;
- fetch/product-page evidence;
- canonical match and validation result;
- persisted offer/raw/audit identifiers;
- refresh workflow URL and price-history evidence;
- catalog search request/response and outbound-network assertion.

The six-store acceptance gate is complete only when all six stores pass the ingestion and refresh checks and the same persisted offers are correctly returned by catalog-first search. A parser unit test, isolated live page fetch, scheduled queue insertion or successful API response alone is not end-to-end acceptance.

## Rollback and release boundary

- Do not merge or deploy merely because this runbook is complete.
- Stop publication for a store if identity, currency, price or availability evidence is inconsistent.
- Keep that store quarantined while other approved stores continue independently.
- Require explicit review of the evidence matrix, backup/restore status, queue health and rollback procedure before production activation.

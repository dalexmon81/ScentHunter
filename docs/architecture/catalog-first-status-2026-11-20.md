# ScentHunter catalog-first architecture status — 2026-11-20

## Executive decision

The catalog-first foundation is implemented in the reconciled architecture branch and is under CI verification in PR #799. It is **not yet a production cutover**. Keep the legacy search path and production data intact until the operational gates below are met.

## Implemented in the architecture foundation

- Canonical SQLAlchemy catalog with Alembic revisions through `0005_connector_quarantine`.
- Shared normalization that preserves concentration, size and sellable-format distinctions, including unknown versus explicitly false flags.
- Database-native canonical variant matching with auditable match outcomes.
- Shared StoreConnector contract and adapters for the authorized Notino CJ feed plus supported legacy scrapers (Deloox, Sabina, Easycosmetic and Parfumzentrum); Bplatz persistence remains separately guarded.
- Staging, validation, promotion, price-history persistence, connector health and explicit quarantine/reactivation.
- Persistent SQLite queue and single-process worker for the isolated single-machine pilot. Celery/Redis queue configuration is present for a later multi-worker deployment; Redis is not the pilot's active queue.
- Read-only catalog API and browser demo. Search handlers query the internal catalog and do not initiate retailer scraping.
- PostgreSQL schema/import compatibility workflows and regression tests.

## Last operational pilot evidence

The latest recorded isolated-pilot verification (2026-11-19) reported:

- 1,403 canonical products and 539 variants.
- 170 published offers: 149 Notino.fr and 21 Bplatz.
- 2 active offers that did not pass the publication gate.
- 36,095 Notino CJ feed records scanned in the ingestion smoke run.

The 36,095 figure is a raw feed scan count, **not** a count of unique, valid, canonicalized or purchasable offers. The 149 Notino offers are the published subset, not the full Notino inventory. A full-feed breakdown by parser validity, deduplication, currency evidence, canonical matching and publication outcome remains a separate measurement task.

## Explicitly not complete

1. **Frontend cutover:** the default frontend still uses the legacy `/search-start` path. The canonical path is opt-in. Do not change the default in this PR.
2. **Production database:** the isolated pilot uses persistent SQLite. PostgreSQL compatibility is tested in CI, but a production PostgreSQL migration and verified restore are not evidenced.
3. **Retailer coverage:** the pilot has Notino and Bplatz provisioned. The four legacy adapters are available but require explicit store provisioning and operator-approved query seeds. The remaining scraper packages are not automatically considered covered.
4. **Search and ranking:** catalog search is database-backed and conservative; full-text search infrastructure and the planned multi-factor offer ranking are not complete.
5. **Operations:** production backup/restore rehearsal, canary rollout, rollback proof, alerting and the 5/20/50/100% traffic migration are pending.
6. **Notino coverage measurement:** the detailed full-feed audit is not a release gate for the architecture foundation and must not block the core PR indefinitely. It must be completed as a separate read-only operational task before making claims about total Notino coverage.

## Merge gate for PR #799

- Required regression workflows on the reconciled head complete successfully.
- Alembic upgrade is repeatable and the canonical catalog import is idempotent on disposable PostgreSQL.
- Connector, worker, matching, normalization, parser and hydration regressions pass.
- The PR diff is reviewed; production deployment and frontend default cutover remain disabled.

## Next milestone after the foundation

1. Finish the isolated Notino full-feed coverage report with aggregate counts and rejection reasons.
2. Provision and measure the remaining retailers one at a time, without weakening publication validation.
3. Complete PostgreSQL production migration only after backup and restore are rehearsed.
4. Run the canonical frontend in shadow/canary mode, prove rollback, then decide on the default cutover.

## Safety invariants

- Do not delete `product_catalog.json`, `family_registry.json`, legacy scrapers or the monolithic legacy runtime as part of this foundation merge.
- Do not publish offers with guessed identity, stock, URL, price or currency.
- Do not run broad retailer scraping inside user-search requests.
- Do not treat raw feed rows, deduplicated products, matched variants and published offers as interchangeable counts.

# Phase 0 — Retailer inventory and access evidence

This inventory is a repository-level preparation artifact. It distinguishes connector code being present from permission and successful live ingestion. A connector file or offline fixture is not evidence of retailer authorization or production readiness.

## Agreed operational scope

Exactly these nine retailers are in scope: bplatz, deloox, easycosmetic, notino, orioudh, parfumcity, parfumzentrum, perfumemarket, sabina.

Amazon DE and Amazon FR are excluded from the Phase 0 scope and must not be scheduled or counted.

## Connector implementation inventory

| Retailer key | Connector module | Code present | Live authorization / operational evidence |
|---|---|---:|---|
| bplatz | `backend/app/connectors/bplatz.py` | Yes | Permission previously recorded as pending; no live ingestion accepted |
| deloox | `backend/app/connectors/deloox.py` | Yes | Prior HTTP 403 recorded; no bypass permitted; live ingestion not accepted |
| easycosmetic | `backend/app/connectors/easycosmetic.py` | Yes | Offline connector implementation exists; live permission and successful live ingestion not verified |
| notino | `backend/app/connectors/notino.py` | Yes | CJ/VIV feed approval and entitlement previously recorded as pending; public-page fallback must obey normal access controls; no live offer accepted |
| orioudh | `backend/app/connectors/orioudh.py` | Yes | Offline connector implementation exists; live permission and successful live ingestion not verified |
| parfumcity | `backend/app/connectors/parfumcity.py` | Yes | Offline connector implementation exists; live permission and successful live ingestion not verified |
| parfumzentrum | `backend/app/connectors/parfumzentrum.py` | Yes | Offline connector implementation exists; live permission and successful live ingestion not verified |
| perfumemarket | `backend/app/connectors/perfumemarket.py` | Yes | Offline connector implementation exists; live permission and successful live ingestion not verified |
| sabina | `backend/app/connectors/sabina.py` | Yes | Offline connector implementation exists; live permission and successful live ingestion not verified |

Runtime construction for all nine is centralized in `backend/app/connectors/runtime_registry.py`. Discovery terms default to an empty object; this is not evidence that any retailer is actively scheduled.

## Data and baseline readiness

- The Phase 0 baseline worker is implemented in `backend/phase0_baseline_worker.py` and `backend/scenthunter_next_engine/phase0_baseline_jobs.py`.
- Its scope is fixed to the nine retailer keys above and it exports offer-level rows with canonical match and validity fields.
- The worker reads the legacy SQLite store catalog (`SCENTHUNTER_CATALOG_DB`, default `backend/store_catalog.sqlite3`), not the new PostgreSQL catalog.
- A baseline CSV has not been evidenced as generated and reviewed on the current operational dataset. Do not treat the worker smoke CSV as a real offer baseline.
- The latest recorded staging seed snapshot is 60 brands, 1,389 fragrances, 512 variants, zero configured stores and zero offers. This is a catalog seed snapshot, not retailer coverage.
- The current repository includes a disposable-local PostgreSQL backup/restore rehearsal. It is deliberately restricted to loopback CI databases with a `ci_restore_*` target. It is not a backup or restore of persistent staging or production.

## Required evidence to close Phase 0

1. Obtain explicit, documented authorization and source access for at least the intended pilot retailer. Do not bypass HTTP 403/429, challenges, or other access controls.
2. Generate the full nine-store offer-level baseline from the intended operational data source; retain explicit zero rows and failed-store statuses.
3. Review and attach counts for offers, valid price/currency/URL/availability, canonical match outcomes, duplicate keys, freshness and per-store coverage.
4. Perform and record a backup and restore rehearsal against the actual persistent staging environment, with an approved target and verified row counts / migration revision. Production is not required for this phase if staging is the agreed pre-operational target, but a disposable CI database alone is insufficient.
5. Confirm the branch ruleset and retain evidence that changes to the default branch require a pull request and cannot be deleted or force-pushed.

## Safety boundary

This inventory does not authorize retailer requests, store activation, persistent database migrations, deployments, feature-flag changes, canary traffic or production operations. Use offline fixtures until the relevant access and environment approvals exist.

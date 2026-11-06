# Phase 0 — Retailer inventory and access evidence

This is a repository-level architecture inventory. It distinguishes connector code from retailer permission and successful live ingestion.

## Agreed scope

Exactly nine retailers are included in the baseline inventory:

bplatz, deloox, easycosmetic, notino, orioudh, parfumcity, parfumzentrum, perfumemarket, sabina.

Amazon DE and Amazon FR are excluded and must not be scheduled or counted.

## Connector implementation inventory

| Retailer key | Connector module | Code present | Live authorization / operational evidence |
|---|---|---:|---|
| bplatz | `backend/app/connectors/bplatz.py` | Yes | Permission previously recorded as pending; no live ingestion accepted |
| deloox | `backend/app/connectors/deloox.py` | Yes | Prior HTTP 403 recorded; no bypass permitted; live ingestion not accepted |
| easycosmetic | `backend/app/connectors/easycosmetic.py` | Yes | Offline implementation exists; live permission and ingestion not verified |
| notino | `backend/app/connectors/notino.py` | Yes | CJ/VIV feed approval and entitlement pending; no live offer accepted |
| orioudh | `backend/app/connectors/orioudh.py` | Yes | Offline implementation exists; live permission and ingestion not verified |
| parfumcity | `backend/app/connectors/parfumcity.py` | Yes | Offline implementation exists; live permission and ingestion not verified |
| parfumzentrum | `backend/app/connectors/parfumzentrum.py` | Yes | Offline implementation exists; live permission and ingestion not verified |
| perfumemarket | `backend/app/connectors/perfumemarket.py` | Yes | Offline implementation exists; live permission and ingestion not verified |
| sabina | `backend/app/connectors/sabina.py` | Yes | Offline implementation exists; live permission and ingestion not verified |

Runtime construction is centralized in `backend/app/connectors/runtime_registry.py`. Discovery terms default to an empty object; this is not evidence that a retailer is actively scheduled.

## Architecture evidence

- The baseline worker is implemented in `backend/phase0_baseline_worker.py` and `backend/scenthunter_next_engine/phase0_baseline_jobs.py`.
- Its scope is fixed to the nine retailer keys and it exports offer-level rows with canonical match and validity fields.
- The worker currently reads the legacy SQLite store catalog (`SCENTHUNTER_CATALOG_DB`, default `backend/store_catalog.sqlite3`), not the new PostgreSQL catalog. This is a known integration limitation, not an operational baseline.
- The repository contains a deterministic CSV quality validator and offline regression tests.
- The combined PostgreSQL vertical-slice workflow passed on 2026-11-06, including disposable PostgreSQL backup/restore, schema/migrations, connectors, ingestion, matching, search, admin queues and rollout safety checks. This is CI evidence only.
- The latest recorded staging seed snapshot is 60 brands, 1,389 fragrances, 512 variants, zero configured stores and zero offers. It is a catalog seed snapshot, not retailer coverage.

## Operational evidence deferred until after Phases 0–11

The following are intentionally not prerequisites for continuing architecture implementation. They are required before real user testing:

1. Approved live source access for retailers selected for activation; no bypass of access controls.
2. A generated and reviewed offer-level baseline from the approved operational data source, with explicit zero/failure rows.
3. Per-store counts and quality review for prices, currencies, URLs, availability, canonical matches, duplicates and freshness.
4. Backup/restore rehearsal against persistent staging, with target, row counts and migration revision recorded.
5. Populated staging API and frontend proven to use the same PostgreSQL catalog.
6. Operational exercise of metrics, alert delivery, quarantine recovery, human review, shadow comparison and rollback.

Notino's feed entitlement remains pending. This does not block architecture implementation or fixture-based CI. Notino real-offer coverage remains a release-readiness gate if Notino is part of the activated retailer scope.

## Safety boundary

This inventory does not authorize retailer requests, store activation, persistent database migrations, deployments, traffic changes or production operations. Use offline fixtures until access and environment approvals exist.

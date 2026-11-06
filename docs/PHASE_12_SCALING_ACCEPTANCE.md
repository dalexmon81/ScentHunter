# Phase 12 — Scaling and new-market acceptance

## Purpose

Make ScentHunter extensible to additional retailers, countries and currencies without
reintroducing retailer-specific logic into the API, search path, canonical catalog or
deployment configuration. Phase 12 is an architecture and verification gate; it does
not authorize live retailer access, store activation, database migration or deployment.

## Non-negotiable architecture rules

1. **Connector isolation**
   - Every retailer is implemented behind the shared `StoreConnector` contract.
   - A connector may discover and parse source evidence; it must not write directly to
     canonical product or published-offer tables.
   - Persistence, normalization, matching, validation and publication remain owned by
     shared ingestion services and workers.
   - A connector failure, timeout, rate limit or quarantine must not stop other stores.

2. **Explicit source authorization**
   - A store cannot be activated merely because a connector exists or its fixture passes.
   - Activation requires documented permission or a verified public/API/feed basis,
     an approved access method, rate limits, terms review and an owner for credentials.
   - HTTP 401/403/429, bot challenges and access-denied responses are hard stop signals.
     No proxy rotation, challenge bypass or retry storm is permitted.
   - Credentials are scoped per store and must never appear in logs, fixtures or API output.

3. **Market-aware data**
   - Store identity is separate from country/market identity.
   - Each store-market configuration declares supported country, currency, locale,
     shipping destination, tax/display convention and source timezone where relevant.
   - Currency validation must use a centrally maintained supported-currency registry;
     a three-letter shape check alone is insufficient for publication.
   - Prices in different currencies must never be compared without an explicit,
     timestamped FX policy. The default is to keep them in separate comparison groups.
   - Product identity remains global; retailer offers and availability remain
     market-specific.

4. **Shared publication and freshness policy**
   - All connectors feed the same raw-evidence → normalized → matched → validated →
     published lifecycle.
   - Store-specific freshness TTLs must be evidence-based and explicitly configured.
     Missing or expired freshness policy means an offer cannot be published or served.
   - Unknown availability, ambiguous identity, invalid currency, missing URL or
     non-positive price must remain out of the published search index.
   - Reprocessing must be idempotent and preserve source evidence and audit history.

5. **Capacity and fault isolation**
   - Discovery, offer refresh, matching and publication have separate queue controls.
   - Per-store concurrency, request rate, timeout, retry budget and circuit/quarantine
     thresholds are configurable and bounded.
   - Dead-letter replay is explicit, observable and safe to repeat.
   - Backpressure for one retailer must not starve other retailers or interactive search.
   - Search remains read-only against the internal catalog and never waits for a retailer.

6. **Operational observability**
   - Metrics are available by store and market: discovery volume, parsed records,
     valid offers, match outcomes, publication/rejection counts, freshness, latency,
     retry rate, quarantine state and last successful run.
   - Alerts cover prolonged sync failure, sudden coverage loss, stale offers,
     rising ambiguity, repeated authorization/rate-limit failures and queue backlog.
   - Dashboards and runbooks identify the responsible connector, market, last good run,
     safe pause procedure and recovery/replay procedure without exposing secrets.

## Required automated verification

- Contract tests for every connector implementation, including malformed payloads,
  missing fields, invalid URLs, currency, availability and timezone handling.
- Isolation tests proving one connector's exception/quarantine does not block another.
- Idempotency and concurrency tests for duplicate discovery, repeated observations,
  overlapping runs and replay from dead-letter queues.
- Market tests proving offers are scoped to the correct destination/currency and that
  cross-currency ranking is blocked unless an explicit FX policy is supplied.
- Freshness tests proving missing/expired TTL offers cannot be published or returned.
- Security tests proving credentials and raw task arguments are not exposed.
- Search tests proving no connector/network call occurs in the user request path.
- Load tests for bounded queue concurrency, backpressure and search latency under
  ingestion load.
- End-to-end tests for adding a new store using only configuration + connector
  implementation, without editing shared search or canonical identity logic.

## Required operational acceptance evidence (after architecture is ready)

- A source-authorization record and approved configuration for each live store.
- A populated staging catalog with representative offers across each enabled market.
- Measured matching precision/recall and reviewed ambiguity samples.
- Successful staging alert, quarantine, recovery and replay exercises.
- Persistent staging backup/restore rehearsal and documented recovery time.
- Shadow comparison and rollback rehearsal before any user traffic is shifted.

## Definition of done

Phase 12 is accepted only when all architecture rules are implemented, all relevant
automated checks pass on the same integrated release candidate, and the operational
evidence above is attached for every market/store being enabled.

A new country, currency or retailer is not considered supported merely because its
configuration can be entered. It is supported only after source authorization,
market policy, connector contract, representative data and acceptance evidence pass.

## Current status

**Not accepted.** The repository already has a shared connector contract, ingestion
workers, per-store status/metrics, offer freshness policy and offline fixtures. The
acceptance evidence above is not yet complete: real source authorization, populated
multi-market staging data, supported-currency policy, measured real-catalog matching
quality, load testing and operational recovery evidence remain outstanding.

This document defines the gate; it does not claim that the gate has been met.

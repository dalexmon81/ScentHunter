# Retailer capability registry

Status: development metadata only — no retailer is activated by this file.

The registry in `backend/app/connectors/registry.py` is the single inventory
of the nine intended retailers. It describes adapter code and worker-dispatch
coverage separately. It is deliberately not a scheduler, health registry,
database seed, or authorization switch.

## Current code coverage

| Retailer | Adapter | Canonical store slug | Worker stages | Readiness |
| --- | --- | --- | --- | --- |
| Bplatz | `app.connectors.bplatz` | `bplatz` | discover, fetch, refresh | worker registered (schedule disabled) |
| Deloox | legacy scraper wrapper | `deloox-be` | discover, fetch, refresh | worker registered |
| Easycosmetic | legacy scraper wrapper | `easycosmetic-de` | discover, fetch, refresh | worker registered |
| Notino | authorized CJ/VIV feed | `notino-fr` | discover, fetch, refresh | worker registered |
| Orioudh | `app.connectors.orioudh` | not established | — | adapter only |
| Parfumcity | `app.connectors.parfumcity` | not established | — | adapter only |
| Parfumzentrum | legacy scraper wrapper | `parfumzentrum-de` | discover, fetch, refresh | worker registered |
| PerfumeMarket | `app.connectors.perfumemarket` | not established | — | adapter only |
| Sabina | legacy scraper wrapper | `sabina-es` | discover, fetch, refresh | worker registered |

“Worker registered” means the current Python worker dispatcher has handlers
for the retailer's existing three stages. It does not mean its store row is
seeded, discovery is enabled, a schedule is running, or a live feed has been
verified.

“Adapter only” means adapter code exists and has fixture tests, but it is not
connected to the worker dispatcher. It must not be presented as operational.

## Activation prerequisites for every retailer

Before a retailer can be considered operational, all of the following need
separate evidence:

1. A reviewed canonical store slug and seed mapping.
2. Adapter contract tests for identity, price precision, currency provenance,
   explicit stock states, malformed source records, timeouts, and changed
   source structure.
3. A worker dispatch mapping for bounded discovery, fetch, and refresh.
4. Idempotent staging, matching, promotion, and price-history behavior.
5. Per-retailer rate/concurrency limits, retry policy, quarantine and operator
   reinstatement behavior.
6. Explicit operator-approved discovery query seeds and an opt-in switch.
7. Disposable-database and broker-backed recovery tests before multi-worker use.
8. A separate runtime approval after database identity, backup/restore and
   rollback evidence are complete.

The four legacy scraper implementations remain authoritative for their page
parsing and are wrapped, not rewritten. The four adapter-only retailers must
be integrated one at a time after their stable store identities and currency
evidence are established. Never infer a missing store slug or default currency
from a retailer domain.

## Non-goals

This inventory does not:
- call a retailer or perform scraping;
- seed or activate a store row;
- register a worker or schedule;
- enable any environment variable;
- change the production runtime or database;
- assert current retailer health or offer freshness.

## Isolated connector security verification (2026-11-21)

The Bplatz, Orioudh, Parfumcity and PerfumeMarket adapters now validate product
URLs against their own retailer hostnames during discovery and before product
fetch. Foreign hosts and lookalike domains are not accepted. Bplatz additionally
disables automatic redirects and rejects redirect responses rather than
following an untrusted destination.

These checks are adapter-level boundaries, not a substitute for network
egress restrictions. They do not authorize retailer activation or live
ingestion. The three adapter-only retailers remain unregistered because their
canonical store slugs have not been established in the canonical seed.

Verified on the isolated branch by PostgreSQL CI workflow #924, including the
host-allowlist regression tests and the full existing compatibility suite:
https://github.com/dalexmon81/ScentHunter/actions/runs/44881500247

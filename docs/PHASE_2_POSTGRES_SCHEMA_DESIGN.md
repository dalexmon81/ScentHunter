# Phase 2 — canonical catalog schema design

**Status:** read-only inventory and schema design; no migration has been applied to Neon.
**Base:** `phase1-catalog-boundary-tests-2026-11-24` (Phase 1 PR #918).
**Purpose:** make PostgreSQL the canonical product identity store without duplicating existing tables or disturbing the operational queue/history.

## 1. Safety boundary

The live Neon inventory is read-only. Do not run DDL, backfills, cleanup, queue retries, status repair, or branch deletion against the operational database as part of this design step.

The prior Phase 0 restore condition remains open: the operational offer-first database has backup/clone branches, but a complete application restore drill has not been proven. Phase 2 migrations must first run against disposable PostgreSQL in CI. Any Neon migration requires a separate approved, branch-specific change after restore evidence is complete.

## 2. Identify the correct Neon database

Neon project: `Scenthunter` (`square-math-01119225`), region `aws-eu-central-1`.

| Neon branch | Database | Role |
|---|---|---|
| `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`) | `scenthunter_offerfirst` | Operational application database. The prior Fly runtime audit identified this database/branch as the Fly-connected PostgreSQL target. |
| `production` (`br-dry-water-ban3a63s`, default) | `neondb` | Separate legacy/default dataset; not the operational catalog used by Fly. |
| `offer-first-postgres-cutover` | `neondb` | A second database on the same branch, with additional tables not present in `scenthunter_offerfirst`. Do not confuse the two databases. |

A read-only count on the default `production/neondb` database returned 73 brands, 3,579 fragrances, 853 variants, and zero stores, offers, price history, raw ingestion rows or ingestion runs. This is a different dataset.

The operational database is `offer-first-postgres-cutover/scenthunter_offerfirst`. Its current Alembic version is `0006_postgres_ingestion_queue`.

## 3. Existing operational schema — reuse, do not recreate

Read-only inspection of `scenthunter_offerfirst` found these tables:

| Existing table | Current responsibility | Phase 2 decision |
|---|---|---|
| `brands` | Canonical brand identity, unique slug and normalized name | Keep; add persisted brand aliases separately. |
| `fragrances` | Canonical fragrance identity linked to brand | Keep; add persisted fragrance aliases separately. |
| `product_variants` | Concentration, size, format flags, GTIN and canonical key | Keep; add variant aliases and a multi-GTIN evidence table. |
| `stores` | Retailer identity, domain, country, status and connector health | Keep. |
| `offers` | Current retailer offer, current price/availability and canonical variant link | Keep as the current offer state; link it to a stable store-product record. |
| `price_history` | Historical price/availability observations per offer | Keep. |
| `ingestion_raw` | Raw retailer observations, external IDs, match/rejection state and JSON payload | Keep; link observations to store products. |
| `ingestion_runs` | Existing store-level aggregate run lifecycle and counters | Keep as the parent/legacy aggregate; do not replace its history. |
| `match_audit` | Match method, confidence, review and canonical variant decision | Keep. |
| `ingestion_queue_jobs` | Durable PostgreSQL queue with discover/fetch/refresh stages | Keep; stage expansion belongs to the queue/automation phase. |
| `ingestion_queue_schedule` | Daily schedule deduplication | Keep. |
| `legacy_product_id_map`, `legacy_variant_id_map` | Compatibility mapping to old catalog IDs | Keep until the migration/rollback phase explicitly retires them. |
| `alembic_version` | Migration version | Current value: `0006_postgres_ingestion_queue`. |

Do not create duplicate `brands`, `fragrances`, `product_variants`, `stores`, `offers`, `price_history`, `match_audit`, `ingestion_runs` or queue tables.

### Current point-in-time counts

These are live read-only counts at the time of this audit; queue and ingestion totals can change while workers run.

| Entity | Rows |
|---|---:|
| Brands | 65 |
| Fragrances | 1,403 |
| Product variants | 556 |
| Stores | 10 |
| Offers | 167 |
| Price history | 9,369 |
| Raw ingestion records | 50,217 |
| Ingestion runs | 52,341 |
| Match audit | 262 |
| Ingestion queue jobs | 176,055 |
| Queue schedule keys | 10 |
| Legacy product ID mappings | 1,417 |
| Legacy variant ID mappings | 547 |

All 167 current offers have a store external product ID and URL, and each `(store_id, external_product_id)` pair is unique. All 167 are currently linked to a canonical variant. The offer source distribution is 108 Notino CJ/VIV, 28 Bplatz, 24 Sabina and 7 Parfumzentrum. Six store rows are active; Deloox.be and Easycosmetic.de currently have no active offers.

The raw observation table contains 33,189 distinct `(store_id, external_product_id)` identities. Its JSON payload includes a product URL and title/name in 41,103 of 50,217 rows. A direct product URL is present in 41,103 raw rows, a title/name in 41,103 rows, and a GTIN key in 37,275 raw rows.

Current ingestion-run states: 9,407 completed, 19 failed, 42,890 partial and 25 running. Queue jobs total 176,055; 74,382 fetch jobs are queued. These are operational state, not cleanup candidates. Do not retry, delete, reclassify or reset them as part of Phase 2 schema work.

## 4. Gaps against the requested Phase 2 entities

| Requested entity/capability | Current state | Gap |
|---|---|---|
| Brands | `brands` exists | No persisted brand alias table. |
| Fragrances | `fragrances` exists | No persisted alternative-name/locale alias table. |
| Product variants | `product_variants` exists | Only one nullable GTIN column; no GTIN provenance/history or variant alias table. |
| Stores | `stores` exists | Reuse existing store registry. |
| Store products | No dedicated table in `scenthunter_offerfirst` | Store identity is embedded in `offers` and repeated in `ingestion_raw`; add a stable store-product entity. |
| Offers | `offers` exists | Add a nullable compatibility link to `store_products`, then backfill and validate before making it required. |
| Price history | `price_history` exists | Reuse; preserve all existing rows. |
| Discovery runs | No separate table | Existing `ingestion_runs` aggregates discovery and offer counters; add stage-specific child runs. |
| Extraction runs | No separate table | Add per-product fetch/extraction evidence linked to the parent ingestion run and store product. |
| Match audit | `match_audit` exists | Reuse; aliases/GTIN matching should continue recording its method and evidence. |
| Ingestion queue | `ingestion_queue_jobs` and schedule exist | Reuse; adding matching/validation/price/availability stages is a later queue phase, not a second queue. |

The same Neon branch also contains a separate `neondb` database with tables such as `canonical_identity_reviews`, `ingestion_artifacts`, `ingestion_dead_letters`, `store_authorizations`, `store_shipping_rates` and user tables. Those tables are not in `scenthunter_offerfirst` and are not represented by the current `backend/app/models` metadata. They must not be treated as part of the Fly application database or silently copied into it.

## 5. Proposed additive model

### 5.1 Stable store product

Add `store_products`:

- `id` UUID primary key.
- `store_id` FK to `stores`.
- `external_product_id` required retailer-native identifier.
- `canonical_url` nullable, validated by the connector boundary.
- `raw_title` nullable.
- `canonical_variant_id` nullable FK to `product_variants`; null means unresolved.
- `first_seen_at`, `last_seen_at`, `status`, `created_at`, `updated_at`.
- Unique `(store_id, external_product_id)`; indexes for store/status and last-seen refresh.

Add nullable `store_product_id` FKs to `ingestion_raw` and `offers`. Keep the existing `store_id`, `external_product_id`, URL and variant columns during the compatibility period. Backfill store products from distinct raw `(store_id, external_product_id)` pairs, using the direct raw payload `product_url` and title/name keys only when present; raw `url` and `affiliate_url` can be affiliate redirects and are never promoted to canonical URLs. Then link current offers. Do not delete the legacy columns in this phase.

Expected initial backfill: up to 33,189 store-product identities from `ingestion_raw`; all 167 current offers have IDs and can be linked. The migration must report unmatched identities rather than inventing IDs.

### 5.2 Persisted aliases

Add separate tables rather than a polymorphic alias table with an unenforced entity foreign key:

- `brand_aliases` → `brands`
- `fragrance_aliases` → `fragrances`
- `product_variant_aliases` → `product_variants`

Each stores the original alias, normalized alias, locale, alias type, source/evidence, verification state and timestamps. Use per-entity uniqueness to prevent duplicate rows for the same entity, but do not enforce global alias uniqueness: the same text may legitimately be ambiguous across brands/products and must return multiple candidates for review.

### 5.3 GTIN evidence

Add `product_variant_gtins` with variant FK, normalized GTIN, market/locale, source, evidence reference, verification state, primary flag and timestamps. Keep `product_variants.gtin` for compatibility and backfill its existing 12 values as legacy-sourced records. Do not promote GTINs found in raw retailer payloads automatically.

Current data has 12 populated variant GTINs, all distinct and numeric, out of 556 variants. Raw ingestion payloads contain GTIN keys in 37,275 rows. A GTIN lookup index is required; a global unique constraint should apply only to verified GTIN mappings after duplicate/market evidence is reviewed.

### 5.4 Stage-specific run evidence

Keep `ingestion_runs` as the historical parent/aggregate. Add:

- `discovery_runs`: parent ingestion run, store, query/category/source, page/cursor information, discovered/new product counts, status, start/end and error evidence.
- `extraction_runs`: parent ingestion run, store, store product, requested URL, HTTP status, parser version, response hash, extracted timestamp, status and error evidence.

Do not fabricate discovery/extraction rows from old aggregate counters. Historical `ingestion_runs` remain untouched; the new tables begin collecting stage-level detail when the new worker path is activated.

### 5.5 Queue boundary

The existing queue is the only queue. Phase 2 must not create a second queue or mutate existing jobs. Stage expansion for match, validation, price refresh and availability refresh belongs to Phase 7, preserving existing stage names and job history.

## 6. Migration order and acceptance tests

1. Add SQLAlchemy models and an Alembic revision after `0006_postgres_ingestion_queue`.
2. Create alias/GTIN evidence tables, `store_products`, `discovery_runs` and `extraction_runs` additively.
3. Add nullable `store_product_id` links to `ingestion_raw` and `offers`.
4. Backfill `store_products` from distinct raw store/external IDs, preserving first/last seen timestamps and extracting URL/title only from known payload keys.
5. Link existing offers to store products; assert all 167 current offers link exactly once and retain their offer IDs, price, currency, availability and price-history references.
6. Backfill the 12 existing variant GTINs as legacy-sourced evidence; do not automatically verify raw GTIN candidates.
7. Add tests for alias ambiguity, normalized lookup, GTIN validation/provenance, store-product deduplication, null/unknown IDs, run parent-child lifecycle and queue compatibility.
8. Run Alembic upgrade twice on disposable PostgreSQL; verify the second upgrade is a no-op.
9. Test downgrade on a disposable database and verify it drops only the new Phase 2 structures/links, not pre-existing catalog, offer, queue or history data.
10. Import a representative catalog and verify counts, foreign keys, indexes, and matching fixtures. Production Neon remains unchanged.

### Phase 2 acceptance gate

- Existing core tables are reused; no duplicate catalog/queue tables.
- All existing offers and price-history rows survive the migration unchanged.
- All current offers receive exactly one store-product link.
- Unresolved aliases/GTINs remain reviewable and cannot create an automatic wrong match.
- Discovery and extraction runs are separately traceable without rewriting old ingestion-run history.
- PostgreSQL migration and rollback tests pass on disposable infrastructure.
- No Neon production DDL/backfill until the separate restore gate and explicit release approval are satisfied.

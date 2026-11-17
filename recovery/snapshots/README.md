# ScentHunter recovery snapshot — 2026-11-17

This directory preserves source data from the open draft pull request #425 without activating it in the application.

## Source
- Repository: `dalexmon81/ScentHunter`
- Source branch: `catalog/brand-expansion-2026-11`
- Source commit: `54d84edabd927f5c6a60616e176adc02a81b3af6`
- Pull request: https://github.com/dalexmon81/ScentHunter/pull/425 (open, draft; NOT merged)

## Preserved files
| Snapshot | Original path | Source blob |
|---|---|---|
| `recovery/snapshots/product_catalog.pr425.json` | `backend/product_catalog.json` | `b4cbbab6cb31c8d209ccd0802909cf88d91b74a1` |
| `recovery/snapshots/family_registry.pr425.json` | `backend/family_registry.json` | `97e952effb069889667cf9fe9b66e5ece1b58d18` |
| `recovery/snapshots/verified_gtin_variant_map.pr425.json` | `backend/scenthunter_next_engine/verified_gtin_variant_map.json` | `6a5b4cb6ac2917fe45f4e528c45a8f673de1d2ab` |

## Initial structural checks on source catalog
- 1,668 canonical product rows
- 141 variant rows
- 22 distinct brand labels in the product array
- 31 family-registry entries
- 0 duplicate product IDs
- 0 duplicate variant IDs
- 0 duplicate (product_id, size_ml, concentration) tuples
- 0 orphan variant rows
- 5 verified GTIN mapping records

## Important limitations
- These files are preserved as evidence and recovery inputs only. They are NOT wired into runtime and must NOT be treated as production-ready.
- The PR's own audit document contains older/inconsistent counts; the counts above were computed from the fetched JSON at the source commit.
- Main currently has a non-empty family registry with 9 entries, including Liquid Brun pilot families, and 4 GTIN records. Those current-main records must be reconciled with this snapshot before replacing active files.
- The source seed's tests do not yet validate every provenance, identity, family-registry and GTIN invariant needed for safe integration.
- No production database, offers, retailer connectors, deployment configuration, secrets or live data are changed by this snapshot.

## Recovery rule
Keep this snapshot immutable. Build and test a separate candidate by reconciling it with current `main`; only promote the candidate after full validation and explicit review.

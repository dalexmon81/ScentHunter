# ScentHunter recovery candidate — 2026-11-17

This directory records provenance for the recovery candidate. The canonical files are restored at their runtime paths in this branch; duplicate copies are intentionally not stored here.

## Source
- Repository: `dalexmon81/ScentHunter`
- Source branch: `catalog/brand-expansion-2026-11`
- Source commit: `54d84edabd927f5c6a60616e176adc02a81b3af6`
- Source PR: [#425](https://github.com/dalexmon81/ScentHunter/pull/425) (open, draft; NOT merged)

## Restored runtime-path files
| Runtime path | Source blob |
|---|---|
| `backend/product_catalog.json` | `b4cbbab6cb31c8d209ccd0802909cf88d91b74a1` |
| `backend/family_registry.json` | `97e952effb069889667cf9fe9b66e5ece1b58d18` |
| `backend/scenthunter_next_engine/verified_gtin_variant_map.json` | `6a5b4cb6ac2917fe45f4e528c45a8f673de1d2ab` |

The original source branch and blobs remain unchanged on GitHub. These references preserve the provenance without duplicating large JSON files in this recovery branch.

## Initial structural checks on source catalog
- 1,668 canonical product rows
- 141 variant rows
- 22 distinct brand labels in the product array
- 31 family-registry entries
- 0 duplicate product IDs
- 0 duplicate variant IDs
- 0 duplicate normalized (brand, canonical_name) identities
- 0 duplicate (product_id, size_ml) variant pairs
- 0 orphan variant rows
- 1,668 products have source URLs and a supported identity status
- 5 verified GTIN mappings resolve to existing products and exact variants with matching sizes

## Reconciliation against current main
- All 9 current-main family records are present unchanged in the 31-family source registry; the source registry adds the remaining families and identities.
- All 4 current-main GTIN records are exact matches in the 5-record source registry.
- The current-main `product_catalog.json` was empty; the candidate restores the source seed at the runtime path.
- The current-main catalog-first PostgreSQL/offer pipeline remains present and is not replaced by this JSON seed.

## Important limitations
- This is a draft recovery candidate, not a production release.
- The source audit document in PR #425 contains stale counts; counts above were computed from the exact fetched JSON blobs.
- The source seed has 1,635 `source_listed_name` identities and 33 `source_verified_name` identities. Product-level URL provenance exists, but this does not mean all variants, GTINs or commercial offers are verified.
- No production database, live offer, retailer connector, deployment configuration or secret is changed.

## Recovery rule
Do not merge until GitHub Actions pass, runtime/search behavior is reviewed, and the candidate is compared against the current catalog-first pilot.

# Candidate reconciliation — recovery branch

Status: **isolated recovery candidate; not merged to main and not deployed.**

## Source inputs
- Original recovery base: `main` commit `600e5f939f0657c3ee4cb0f4854828edd9b064e6`.
- Current main also contains the opt-in PostgreSQL guard from PR #774, merge `defe49283754281c81f540fbdc3ef5588097c692`.
- Canonical product/variant seed: PR #425, source commit `54d84edabd927f5c6a60616e176adc02a81b3af6`.
- Cumulative discovery-family harvest: PR #639 head `2362eaa310e2e6a981978ab5a64501831170ce36`, branch `catalog/arabiyat-prestige-new-launch-verification-2026-11-10`, family registry blob `3ee094e336eee206d5b86ca682efba2b6d2dcb58`.
- Verified family-format updates from PR #638 (four Velixir 35/100 ml format hints) and PR #639 (three Arabiyat 100 ml hints plus one 110 ml hint) are included.
- Current-main family safety exclusions are included in the merged registry.

## Candidate runtime-path data on this isolated branch
- `backend/product_catalog.json`: 1,668 canonical product rows, 141 variant rows, 22 brands.
- `backend/family_registry.json`: 34 families, 2,440 product references, 2,366 case/whitespace-normalized brand/name keys; all 1,668 canonical catalog products are covered.
- `backend/scenthunter_next_engine/verified_gtin_variant_map.json`: 5 verified GTIN records; all resolve to exact product/variant IDs and matching sizes.

The family registry combines the cumulative harvest, PR #425 seed and current main. Product entries are merged by case-insensitive, whitespace-normalized canonical name within each family. Aliases and format sizes are unioned. Punctuation and accent variants are not automatically collapsed. Current-main and source exclusion rules are retained.

## Structural validation
- 0 duplicate product IDs; 0 duplicate variant IDs; 0 orphan variants.
- 0 duplicate product-size variant pairs.
- 0 duplicate family IDs.
- 0 case/whitespace-normalized duplicate canonical names within a family.
- 0 canonical catalog products missing from the family registry.
- 0 catalog products referencing an unknown family ID.
- 5/5 GTIN records resolve to existing products and exact variants.

## Known limitations / review gates
- The source seed contains 1,635 `source_listed_name` identities and 33 `source_verified_name` identities. Product-level URL provenance is present, but not every identity has individual product-detail-page evidence.
- Variant evidence is uneven: 53/141 variants have a `source_evidence_url`; 88 do not. Concentration is present on 127/141 variants; 14 remain blank. Do not infer missing concentration or variant provenance from a parent product URL.
- 16 punctuation/diacritic-normalized name-collision groups remain listed in `name-collision-audit.md`. They are deliberately not auto-merged.
- The canonical product seed contains two Giorgio Armani Acqua di Giò Profondo product IDs with separate GTIN-backed variants. They are intentionally kept separate; see the collision audit.
- Cross-family repetition (e.g. Lattafa Asad and French Avenue Liquid Brun in both dedicated and general families) is retained as discovery coverage, not treated as duplicate canonical products.
- The family registry is discovery metadata. It does not create canonical products, variants, commercial offers, prices, stock or shipping costs.
- Do not promote this candidate until the full current-head CI suite and application import/search behavior are reviewed together with the PR #772 Bplatz pilot.

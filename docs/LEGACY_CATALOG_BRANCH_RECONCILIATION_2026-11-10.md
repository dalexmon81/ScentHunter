# Legacy Catalog Branch Reconciliation — 2026-11-10

## Purpose

This note records a data-level comparison of the older cumulative Al Wataniah and Paris Corner audit branches against the current catalog continuation branch used by PR #715. The goal is to avoid reapplying stale catalog snapshots and accidentally overwriting newer evidence or creating duplicate variants.

## Compared refs

- Current continuation: `catalog/armaf-paris-corner-variant-gap-2026-11-10` (PR #715 head, commit `168f511e7c7d724168861ea29dcd99d8be706845`).
- Older Al Wataniah branch: `catalog/al-wataniah-81-variants-cumulative-2026-11-10` (PR #666 head, commit `bbeed92d9d156db8409a4a8962ebe832c5bb25d7`).
- Older Paris Corner branch: `catalog/paris-corner-eleven-details-cumulative-2026-11-10` (PR #667 head, commit `a7f624aa7738ab5f8baa229a461aa91ccf7548f1`).

## Results

### Al Wataniah — PR #666 is already superseded in the current catalog

- Both snapshots contain 86 Al Wataniah canonical product identities.
- All 81 variant IDs present in the older PR #666 snapshot are already present in the current PR #715 snapshot.
- The current snapshot contains 84 Al Wataniah variants, i.e. three more than the older branch.
- The three additional current variants are not copied from the older branch; the current catalog remains authoritative for these records.
- No Al Wataniah product identity or variant needs to be imported from PR #666.

### Paris Corner — PR #667 is already represented, with newer enrichment

- Both snapshots contain 254 Paris Corner canonical product identities.
- All 194 variant IDs in the older PR #667 snapshot are already present in the current PR #715 snapshot.
- The current snapshot contains 218 Paris Corner variants, 24 more than the older branch.
- Four overlapping variant records differ in content. Three have newer official source URL/evidence URL fields in the current snapshot (Green Bet, Heer, The Show Magnifique); Zariya has a concentration value in the current snapshot.
- The current records are retained. The older records must not overwrite them.

## Decision

Do not cherry-pick, copy, or merge the old PR #666/#667 catalog snapshots into the current branch. Their relevant variant IDs are already present, and the current branch contains additional records and/or stronger evidence. Re-importing them would be redundant and could regress provenance.

This reconciliation is a catalog-history audit only. It does not change canonical products, variants, family registry records, offers, prices, stock, availability, shipping, retailer data, or production configuration.

## Validation policy

- Preserve existing canonical product IDs and variant IDs.
- Never infer a size or concentration from a product name alone.
- Keep official source evidence on the individual variant where available.
- Treat the current catalog branch as the source of truth for the continuation; do not use older branch snapshots as replacement files.
- Run the catalog seed validation workflow after any further catalog modification.

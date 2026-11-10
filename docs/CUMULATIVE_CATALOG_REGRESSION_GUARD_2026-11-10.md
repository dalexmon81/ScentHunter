# Cumulative catalog regression guard — 10 November 2026

## Protected baseline

This audit protects the cumulative branch at commit `4e76e1c30be77530ad7b177651d7f85141fcaa47`:

- 2,207 canonical fragrance identities.
- 1,107 explicit product variants.
- 22 brand labels represented.
- 34 family-registry families.
- Zero duplicate product IDs.
- Zero duplicate variant IDs.
- Zero duplicate normalized brand/name identities.
- Zero duplicate product/size/concentration tuples.
- Zero orphan variants.
- Zero variants whose size is absent from the parent product's declared formats.

These are regression baselines, not a claim that the catalog is globally exhaustive.

## Why PR #690 is not merged into this line

PR #690 is based on a different parent snapshot and must not replace the cumulative #689 head.

A direct comparison found:

- The #690 catalog contains 888 variants, 220 fewer than this protected 1,107-variant baseline.
- It downgrades many individual product-page records from `source_verified_name` to `source_listed_name`, replacing product-level URLs with broad collection URLs.
- It introduces a Gulf Orchid attribution for Vanilla Aura and Vanilla Voyage even though the existing canonical identities are Maison Asrar products sold through the Gulf Orchid storefront.
- It adds a second Khadlaj identity named “Musk Pure Musk Blend Creation of Iqbal” alongside the existing canonical “Musk Pure Musk Blend”.
- Its Marwa variant needs a fresh primary-source check before its 100 ml EDP claim can be accepted.

No product or variant records from #690 are copied into this branch by this guard commit.

## New regression coverage

The new test module protects:
- Minimum cumulative product and variant counts.
- Unique canonical IDs, variant IDs, normalized identities and variant tuples.
- Parent/variant linkage and declared size consistency.
- Unique family-registry IDs.
- The four Gulf Orchid 100 ml EDP variants: Maze, Mosaic, Rice Milk and Royal Rose.
- Zimaya Afrah 20 ml Concentrated Oil, Al Embratur Elixir 100 ml EDP and Ghali Imperial 100 ml EDP.
- Khadlaj Cream Velvet 100 ml Extrait de Parfum.
- Maison Asrar attribution for Vanilla Aura and Vanilla Voyage.
- A single canonical Khadlaj Musk Pure Musk Blend identity.

## Next audit priorities

1. Continue official, paginated product-level reconciliation for Paris Corner and Khadlaj.
2. Resolve source-listed identities without inventing bottle sizes or concentrations.
3. Reduce the verified-name/no-variant backlog by adding variants only when primary product pages explicitly support size and concentration.
4. Keep retailer offers, prices, stock and availability out of the canonical identity seed.
5. Keep the branch draft until exact-head CI passes and the audit results are reviewed.

## Safety

This commit changes tests and documentation only. It does not alter catalog records, merge any PR, update `main`, or deploy production.

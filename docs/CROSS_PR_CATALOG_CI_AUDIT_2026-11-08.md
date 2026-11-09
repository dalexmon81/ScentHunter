# Cross-PR catalog CI audit — 2026-11-08

**Repository:** `dalexmon81/ScentHunter`  
**Automation PR:** [#583 — Add combined cross-PR catalog collision audit](https://github.com/dalexmon81/ScentHunter/pull/583)  
**Baseline:** `catalog/requested-brand-harvest-2026-11-08`  
**Candidate PRs inspected:** 22  
**Scope:** read-only comparison of each candidate PR's direct changes against its actual base branch, then cross-PR reconciliation.

## Result

**CI gate: blocked — expected while overlaps remain unresolved.**

The cross-PR audit completed its scan and reported **96 findings**. The job stopped at the audit step, so the existing catalog unit-test step was skipped in this run. This is not a green CI run and must not be described as one.

| Finding type | Count | Meaning |
|---|---:|---|
| Normalized product identity collisions | 14 | Same brand/name represented by different product IDs |
| Variant tuple collisions | 48 | Same product, size and concentration represented by different variant IDs |
| Identical product additions across PRs | 0 | No identical product additions remain in the audited PR set |
| Identical variant additions across PRs | 21 | Same Armaf variant change proposed by multiple PRs |
| Shared family-registry additions | 13 | Same Armaf or Lattafa family/canonical entry added in more than one PR |
| **Total findings** | **96** | Categories can describe the same underlying overlap |

The audit compares each PR against its **actual base branch**. This is important: cumulative descendants are not counted as if all inherited rows were newly added by the descendant PR.

## 1. Product identity collisions — 14

### Armaf — 2

| Canonical identity | Competing product IDs | PRs |
|---|---|---|
| Check Mate White Knight | `SH-ARMAF-5fce992b`; `SH-ARMAF-CHECK-MATE-WHITE-KNIGHT` | #564, #565 |
| Odyssey French Kiss | `SH-ARMAF-1727c712`; `SH-ARMAF-ODYSSEY-FRENCH-KISS` | #558, #565 |

Keep one canonical product identity per fragrance. Preserve both official source URLs as evidence if they refer to the same fragrance.

### Lattafa — 12

| Canonical identity | Competing product IDs | PRs |
|---|---|---|
| Asad Polar | `SH-LATTAFA-ASAD-POLAR`; `SH-LATTAFA-EU-HARVEST-039` | #562, #578 |
| Atlas Canyon | `SH-LATTAFA-ATLAS-CANYON`; `SH-LATTAFA-EU-HARVEST-037`; `SH-LATTAFA-NEW-LAUNCH-ATLAS-CANYON` | #555, #562, #576 |
| Atlas Glacial Valley | `SH-LATTAFA-ATLAS-GLACIAL-VALLEY`; `SH-LATTAFA-EU-HARVEST-038`; `SH-LATTAFA-NEW-LAUNCH-ATLAS-GLACIAL-VALLEY` | #555, #562, #576 |
| Badee Al Oud Amethyst Fusion | `SH-LATTAFA-BADEE-AL-OUD-AMETHYST-FUSION`; `SH-LATTAFA-EU-HARVEST-027`; `SH-LATTAFA-NEW-LAUNCH-BADEE-AL-OUD-AMETHYST-FUSION` | #555, #562, #577 |
| Beyond Precious | `SH-LATTAFA-BEYOND-PRECIOUS`; `SH-LATTAFA-EU-HARVEST-040` | #562, #576 |
| Farfasha | `SH-LATTAFA-EU-HARVEST-035`; `SH-LATTAFA-NEW-LAUNCH-FARFASHA` | #555, #562 |
| Harlequin Cream Give Me Gourmand | `SH-LATTAFA-EU-HARVEST-041`; `SH-LATTAFA-HARLEQUIN-CREAM-GIVE-ME-GOURMAND` | #562, #576 |
| Khamrah Mira | `SH-LATTAFA-EU-HARVEST-047`; `SH-LATTAFA-KHAMRAH-MIRA` | #562, #576 |
| Majd Al Sultan Black Intense | `SH-LATTAFA-EU-HARVEST-033`; `SH-LATTAFA-NEW-LAUNCH-MAJD-AL-SULTAN-BLACK-INTENSE` | #555, #562 |
| Matcha Swirl Give Me Gourmand | `SH-LATTAFA-EU-HARVEST-048`; `SH-LATTAFA-MATCHA-SWIRL-GIVE-ME-GOURMAND` | #562, #576 |
| Petra Viola | `SH-LATTAFA-NEW-LAUNCH-PETRA-VIOLA`; `SH-LATTAFA-PETRA-VIOLA` | #555, #577 |
| Raghad | `SH-LATTAFA-EU-HARVEST-026`; `SH-LATTAFA-NEW-LAUNCH-RAGHAD`; `SH-LATTAFA-RAGHAD` | #555, #562, #576 |

These are identity-level collisions, not proof that every product detail is identical. Reconcile official spelling, product URLs, variants and aliases before selecting the surviving product ID.

## 2. Velixir variant collisions — 48

PRs #465 and #517 independently describe the same **24 Velixir products** and the same two EDP size tuples per product:

- 35 ml Eau de Parfum
- 100 ml Eau de Parfum

That produces **48 duplicated product/size/concentration tuples**. The variant IDs use two different naming schemes:

- `VAR-SH-VELIXIR-...`
- `SHV-SH-VELIXIR-...`

Choose one variant ID per tuple. Do not count the two naming schemes as distinct stock-keeping variants.

## 3. Gulf Orchid overlap — resolved in PR #584

The audit now uses PR #584 in place of the overlapping PR #554. PR #584 is based on PR #542 and carries only seven unique new-arrival additions: Belle, Amour, Chic, Phantom, Flamma, Vortex and Rosalia.

- Cloud 9 and Maestro remain inherited once from PR #542.
- The combined branch contains one product and one 100 ml EDP variant per fragrance.
- The family registry contains the seven additional identities once.
- Vanilla Aura and Vanilla Voyage remain excluded from Gulf Orchid because #542 corrected their brand attribution to Maison Asrar.
- PR #554 remains open/draft but is no longer part of the audit candidate set; it has been identified as superseded by #584.

The resulting combined catalog was checked for unique product IDs, variant IDs, normalized brand/name identities and product/size/concentration tuples. The Gulf Orchid overlap findings have fallen to zero.

## 4. Identical variant additions — 21

**21 Armaf variant concentration updates** are repeated by both #569 and #573. They are the same existing variant IDs and same EDP/source corrections, not 42 distinct corrections.

Keep one change per variant tuple and preserve the best-supported source evidence.

## 5. Shared family-registry additions — 13

| Family | Canonical entries | PRs |
|---|---|---|
| Armaf | Check Mate White Knight; Odyssey French Kiss | #558, #564, #565 |
| Lattafa | Atlas Canyon; Atlas Glacial Valley; Badee Al Oud Amethyst Fusion; Beyond Precious; Farfasha; Harlequin Cream Give Me Gourmand; Khamrah Mira; Majd Al Sultan Black Intense; Matcha Swirl Give Me Gourmand; Petra Viola; Raghad | #555, #562, #576, #577 |

The family registry should contain one canonical row for each fragrance identity. Legitimate alternate spellings belong in aliases, not duplicate canonical rows.

## Recommended reconciliation order

1. **Gulf Orchid #542/#554:** consolidated in #584; seven unique new arrivals are retained without duplicate Cloud 9 or Maestro records.
2. **Velixir #465/#517:** select one stable variant-ID scheme for all 48 repeated tuples.
3. **Armaf #558/#564/#565:** reconcile Check Mate White Knight and Odyssey French Kiss; keep the complementary regional source URLs.
4. **Lattafa #555/#562/#576/#577/#578:** choose one product ID per canonical identity and consolidate aliases, source evidence and variants.
5. **Armaf #569/#573:** retain one copy of the 21 identical variant updates and preserve the strongest regression tests/evidence notes.

## Safety and interpretation

- This audit detects overlaps; it does not automatically decide which source or product ID is authoritative.
- No catalog row, variant, family entry, price, stock, `main` branch or production deployment was changed by the audit.
- All component PRs remain open unless separately changed by an explicit review decision.
- A blocked CI result is the intended signal while these overlaps remain unresolved.

## Follow-up verification — 2026-11-09 (PR #592)

**Latest CI gate: PASS.** The selected 25-PR audit completed with zero conflicting product or variant identities, and the catalog regression suite passed all 136 tests.

- Audit run: [42575614913](https://github.com/dalexmon81/ScentHunter/actions/runs/42575614913)
- Cross-PR audit: `PASS: no conflicting product or variant identities detected.`
- Regression tests: `Ran 136 tests`, `OK`.
- Baseline: 2,061 products, 291 variants and 34 families.
- Candidate set: 25 PRs, direct changes compared with each actual base branch.
- Informational overlap: 115 identical additions across PRs. These share the same canonical product/variant identities and do not represent conflicting IDs; they are reported for review but do not block CI.

### Reconciliations completed

- **Armaf:** Check Mate White Knight and Odyssey French Kiss now use one product ID across the selected source branches. The French Kiss 60 ml EDP variant also uses one variant ID. Dashed spelling remains an alias.
- **Gulf Orchid:** Al Qasr and Riwaya now reuse their pre-existing canonical product IDs. Amour, Belle and Chic use the same canonical IDs across #584, #587, #588 and the stacked #591 integration branch. Sweet Heaven and Sweet Heaven Extreme bottle volume is treated as variant metadata, not as a second product identity.
- **Lattafa:** Asad Polar, Atlas Canyon, Atlas Glacial Valley, Amethyst Fusion, Beyond Precious, Farfasha, Harlequin Cream Give Me Gourmand, Khamrah Mira, Majd Al Sultan Black Intense, Matcha Swirl Give Me Gourmand, Petra Viola and Raghad now use one product ID per normalized identity across the candidate branches. Stacked PR branches were refreshed against their updated bases so inherited rows are not misclassified as new additions.
- **Audit hardening:** trailing metric volume suffixes are excluded from canonical product identity comparison; variant identity continues to include product, size and concentration.

The 115 identical additions are retained as informational evidence because multiple source PRs independently contain the same stable identity. They must not be double-counted when building the consolidated seed. The audit does not silently suppress distinct product IDs or distinct variant tuples.

### Architecture handoff

PR #424 remains separate and open/draft. Its current head `a45a0a1cabf09dd926b5bd158a34dcbd4880a9e0` passed:
- [Catalog-first PostgreSQL vertical slice — run 42574270479](https://github.com/dalexmon81/ScentHunter/actions/runs/42574270479)
- [Catalog-first staging API contract — run 42574270516](https://github.com/dalexmon81/ScentHunter/actions/runs/42574270516)

This is a green catalog collision gate and a green isolated architecture CI slice, not acceptance of all architecture phases or live retailer ingestion. No PR was merged, no live retailer was activated, and no production deployment or traffic rollout was performed.

### Follow-up verification — 9 November 2026 (Al Wataniah PR #604)

PR #604 adds no new canonical identities. It upgrades twelve existing Al Wataniah identities to their individual brand-owned product pages and adds one explicitly documented 100 ml Eau de Parfum variant to each:

- Kayaan Midnight
- Sabah Al Ward
- Sabah Al Ward Sugar
- Special Oud
- Emiran
- Cloud
- Castilla
- Fayroz
- Layali
- Praline Toffee
- Turquois
- Royal Oak II

The original product IDs are preserved. The family registry and two Al Wataniah regression modules were updated to recognize the verified detail pages and the expanded set of explicit variants. CI initially exposed stale assertions that assumed only two Al Wataniah variants existed; those assertions were updated to distinguish detail-verified identities from collection-only identities.

- Catalog validation: [run 42627903917](https://github.com/dalexmon81/ScentHunter/actions/runs/42627903917)
- Result: **PASS — 143 tests, OK**.
- Cross-PR audit candidate set is extended to include PR #604 (27 candidates total); this audit run validates the new candidate set independently.

No new product IDs, retailer offers, prices, stock, shipping or deployment changes are included.

# Cross-PR catalog CI audit — 2026-11-08

**Repository:** `dalexmon81/ScentHunter`  
**Automation PR:** [#583 — Add combined cross-PR catalog collision audit](https://github.com/dalexmon81/ScentHunter/pull/583)  
**Baseline:** `catalog/requested-brand-harvest-2026-11-08`  
**Candidate PRs inspected:** 22  
**Scope:** read-only comparison of each candidate PR's direct changes against its actual base branch, then cross-PR reconciliation.

## Result

**CI gate: blocked — expected while overlaps remain unresolved.**

The cross-PR audit completed its scan and reported **102 findings**. The job stopped at the audit step, so the existing catalog unit-test step was skipped in this run. This is not a green CI run and must not be described as one.

| Finding type | Count | Meaning |
|---|---:|---|
| Normalized product identity collisions | 14 | Same brand/name represented by different product IDs |
| Variant tuple collisions | 48 | Same product, size and concentration represented by different variant IDs |
| Identical product additions across PRs | 2 | Same product ID/identity added independently |
| Identical variant additions across PRs | 23 | Same variant change proposed by multiple PRs |
| Shared family-registry additions | 15 | Same family/canonical entry added in more than one PR |
| **Total findings** | **102** | Categories can describe the same underlying overlap |

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

## 3. Identical product additions — 2

PRs #542 and #554 independently add the same Gulf Orchid products with the same IDs:

- Cloud 9 — `SH-GULF-ORCHID-CLOUD-9`
- Maestro — `SH-GULF-ORCHID-MAESTRO`

Keep one product row per fragrance in the combined catalog.

## 4. Identical variant additions — 23

- **21 Armaf variant concentration updates** are repeated by both #569 and #573. They are the same existing variant IDs and same EDP/source corrections, not 42 distinct corrections.
- **2 Gulf Orchid variants** are repeated by #542 and #554:
  - Cloud 9, 100 ml EDP
  - Maestro, 100 ml EDP

Keep one change per variant tuple and preserve the best-supported source evidence.

## 5. Shared family-registry additions — 15

| Family | Canonical entries | PRs |
|---|---|---|
| Armaf | Check Mate White Knight; Odyssey French Kiss | #558, #564, #565 |
| Gulf Orchid | Cloud 9; Maestro | #542, #554 |
| Lattafa | Atlas Canyon; Atlas Glacial Valley; Badee Al Oud Amethyst Fusion; Beyond Precious; Farfasha; Harlequin Cream Give Me Gourmand; Khamrah Mira; Majd Al Sultan Black Intense; Matcha Swirl Give Me Gourmand; Petra Viola; Raghad | #555, #562, #576, #577 |

The family registry should contain one canonical row for each fragrance identity. Legitimate alternate spellings belong in aliases, not duplicate canonical rows.

## Recommended reconciliation order

1. **Gulf Orchid #542/#554:** remove the two repeated product rows, variant rows and family entries while preserving the genuinely new arrivals from both PRs.
2. **Velixir #465/#517:** select one stable variant-ID scheme for all 48 repeated tuples.
3. **Armaf #558/#564/#565:** reconcile Check Mate White Knight and Odyssey French Kiss; keep the complementary regional source URLs.
4. **Lattafa #555/#562/#576/#577/#578:** choose one product ID per canonical identity and consolidate aliases, source evidence and variants.
5. **Armaf #569/#573:** retain one copy of the 21 identical variant updates and preserve the strongest regression tests/evidence notes.

## Safety and interpretation

- This audit detects overlaps; it does not automatically decide which source or product ID is authoritative.
- No catalog row, variant, family entry, price, stock, `main` branch or production deployment was changed by the audit.
- All component PRs remain open unless separately changed by an explicit review decision.
- A blocked CI result is the intended signal while these overlaps remain unresolved.

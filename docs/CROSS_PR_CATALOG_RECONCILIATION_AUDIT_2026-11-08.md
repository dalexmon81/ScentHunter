# Cross-PR catalog reconciliation audit

**Audit date:** 2026-11-08  
**Repository:** dalexmon81/ScentHunter  
**Scope:** compare open catalog PRs for overlapping canonical identities, variant tuples, source URLs and family-registry entries. This is a review checkpoint, not a merge or catalog mutation.

## Executive summary

The open PR set contains several independent branches that each pass their own catalog validation, but do not all validate the combined state. At least five cross-PR overlap groups require reconciliation before integration.

## Confirmed overlaps

### 1. Gulf Orchid — PR #542 vs PR #554

Two exact duplicate product records are present in both PRs:

| Canonical identity | Product ID | Official source | Variant |
|---|---|---|---|
| Cloud 9 | SH-GULF-ORCHID-CLOUD-9 | https://shop-gulforchid.com/products/cloud-9 | 100 ml EDP |
| Maestro | SH-GULF-ORCHID-MAESTRO | https://shop-gulforchid.com/products/maestro | 100 ml EDP |

The same product IDs and variant IDs are repeated, and the family registry contains repeated canonical entries. PR #554 is also currently reported by GitHub as not mergeable. Its head is six commits ahead and one behind its base branch, so it needs a base/conflict refresh as well as duplicate removal.

**Action:** keep one product row, one variant row and one family-registry entry per fragrance. Rebase/reconcile #554 against the branch containing #542 and retain only genuinely new products.

### 2. Velixir — PR #465 vs PR #517

Both PRs contain the same 24 product IDs and the same official Velixir product URLs. Both also introduce the same 48 product/size/concentration combinations: 35 ml EDP and 100 ml EDP for each of the 24 perfumes.

The variant IDs use different naming schemes:
- PR #465: `VAR-SH-VELIXIR-...`
- PR #517: `SHV-SH-VELIXIR-...`

Different IDs do not make these distinct variants. Combining the branches without reconciliation would create duplicate variant tuples for the same product and size.

**Action:** choose one canonical variant-ID scheme and add a regression test for unique `(product_id, size_ml, concentration)` tuples, not just unique `variant_id`.

### 3. Armaf — PR #564 vs PR #565

Both PRs add the same fragrance from the exact same official page:
- PR #564: `Check Mate White Knight`
- PR #565: `Check Mate White - Knight`
- Official page: https://cz.armaf.eu/en/products/check-mate-white-knight

This is a punctuation-only difference. Keep one canonical identity and the documented 100 ml EDP variant once; use aliases for legitimate spelling differences.

### 4. Armaf — PR #558 vs PR #565

Both PRs add `Odyssey French Kiss` as separate canonical product rows:
- PR #558 product ID: `SH-ARMAF-ODYSSEY-FRENCH-KISS`, source https://armaf.com/products/odyssey-french-kiss
- PR #565 product ID: `SH-ARMAF-1727c712`, source https://cz.armaf.eu/products/odyssey-french-kiss

The regional official page in #565 also documents a 60 ml EDP variant. Retain one canonical product, preserve both regional source URLs as evidence, and attach the 60 ml variant to that product.

### 5. Lattafa — PR #555 vs PR #562

The following identities appear in both expansions:
- Atlas Canyon
- Raghad
- Badee Al Oud Amethyst Fusion
- Farfasha
- Majd Al Sultan Black Intense
- Ramad / Ramaad Al Oud

Reconcile official spelling, canonical identity, aliases, product IDs, variants and source URLs. Do not create a second identity for a spelling variation.

## Overlapping Mykonos source-evidence work

PR #539 and PR #546 both upgrade the same existing Mykonos products from collection-level evidence to official product-detail-page evidence. Fourteen official detail-page URLs occur in both patches. This is overlapping source-evidence work, not by itself proof of duplicate product rows. Select one cumulative branch as the integration path and avoid replaying the same edits independently.


## Aromatix — identity coverage and variant-evidence gap

The base catalog currently contains 12 Aromatix product identities:
Carnal Desire, Forbidden Fruit, Frostbite, Magnetiq, Naughty Dates, Ora,
Platine Blanc, Royal Taboo, Roza, Sun Kissed, Teas Me and X Xandal.
All 12 are marked `source_listed_name`, point to the same Notino Belgium
brand/category page as `source_url`, and cite the Aromatix X French Avenue
Fragrantica designer page as `source_evidence_url`.

The naming/ownership needs to remain explicit rather than being silently
collapsed into a generic Aromatix manufacturer assumption:
- The Fragrantica designer listing identifies the collaboration as
  **Aromatix X French Avenue**, names French Avenue as parent company, and
  lists 12 fragrances, including Ora and Roza (2026).
- Shop Aromatix describes a separate “Signature Aromatix Collection” as a
  ten-fragrance collaboration, and its collection page names those ten
  signature scents. Its current Aromatix X French Avenue product collection
  shows 12 items, but the last two are Summer Vibes Blue and Yellow discovery
  sets (5 x 30 ml), not two additional single-fragrance identities.
- The catalog's two registry families, `aromatix_catalog` (brand Aromatix)
  and `aromatix_french_avenue` (brand French Avenue), contain the same 12
  canonical names. These appear to be dual lookup/alias coverage for one
  collaboration, not 12 additional product identities. Preserve one catalog
  product row per fragrance; make the alias relationship explicit in tests or
  documentation so future harvests do not add duplicate products under
  French Avenue.
- The 12 Aromatix catalog product rows currently have **no variant rows**.
  Retailer pages show 100 ml for the ten signature scents, but concentration
  labels are not consistent: Shop Aromatix presents the ten as EDP, while
  Notino's current listings label some as Extrait and others as EDP. European
  retailer listings also show 100 ml EDP for Ora and Roza. These are
  retailer-level sources, not manufacturer product-detail pages, and the
  concentration conflict means the size/concentration tuple should not be
  guessed. Do not create 100 ml variants as officially verified until a
  suitable primary product source or an approved evidence policy supports
  each exact concentration.

**Action:** keep the 12 identities as one collaboration set; distinguish the
ten original signature scents from the two 2026 launches Ora and Roza; retain
the French Avenue/Aromatix dual-name mapping as aliases, not duplicate
canonical products; and leave variant rows uncreated until the evidence
standard is met.

Evidence checked on 2026-11-08:
- https://www.fragrantica.com/designers/Aromatix-X-French-Avenue.html
- https://www.notino.be/french-avenue/aromatix/
- https://www.notino.be/french-avenue/aromatix-magnetiq-extrait-de-parfum-mixte/
- https://www.notino.be/french-avenue/aromatix-frostbite-eau-de-parfum-mixte/
- https://shoparomatix.com/pages/aromatic-collection
- https://shoparomatix.com/collections/aromatix-x-french-avenue
- https://olvio.co.uk/collections/aromatix-x-french-avenue-collection?sort_by=created-descending

## CI status and limitation

The following individual catalog validation runs were checked and passed:
- PR #554 head: run 42517779599
- PR #517 head: run 42499610167
- PR #465 head: run 42470787169
- PR #546 head: run 42513510773
- PR #562 current head: run 42523314618
- PR #568 cross-PR uniqueness-test head: run 42525428834

These green runs validate each branch separately. They do **not** prove the combined catalog is free of cross-PR duplicate product or variant records.

PR #565's current head still has no workflow run on its exact SHA. Its base branch, `catalog/lattafa-four-official-products-2026-11-08`, is not in the workflow's `pull_request.branches` allowlist; a comment was added to #565 asking for that trigger/validation gap to be addressed.

PR #568 adds automated regression guards for unique normalized product identities, product/variant IDs, variant tuples, orphan variants and exact duplicate rows within each family. Its catalog validation job passed on the exact PR head. These checks validate the candidate tree in which the workflow runs; they do not magically combine all open branches into one tree. No merge has been performed as part of this audit.



## Family-registry normalization debt found in the base snapshot

A separate read-only scan of the exact base-branch registry blob
`6981b9619abf7af30153ea2948035b99c9e2a58d` (34 families) found **18 pairs** of
canonical labels within the same family that collapse to the same normalized
spelling when case, punctuation and diacritics are ignored. The full list is:

- Paris Corner (14): `Deux II Expressions, North Stag` / `Deux II Expressions North Stag`; `Jardin Des Papillons` / `Jardin des Papillons`; `Lueur D'Espoir Arena Intense` / `Lueur d'Espoir Arena Intense`; `Lueur D'Espoir Memories of Summer` / `Lueur d'Espoir Memories of Summer`; `Lueur D'Espoir Serene Grove` / `Lueur d'Espoir Serene Grove`; `Lueur D'Espoir Silhouette` / `Lueur d'Espoir Silhouette`; `Midnight Sin By Daniel Rene` / `Midnight Sin by Daniel René`; `Noir D'Arabie` / `Noir d'Arabie`; `Papillon Des Vents` / `Papillon des Vents`; `Quatre IV Expressions, North Stag` / `Quatre IV Expressions North Stag`; `Rua` / `RUA`; `Taskeen Lactea Divina` / `Taskeen Lactéa Divina`; `Trois III Expressions, North Stag` / `Trois III Expressions North Stag`; `Un I Expressions, North Stag` / `Un I Expressions North Stag`.
- Arabiyat Prestige (2): `Nyla Vani-elle` / `Nyla Vani-Elle`; `Noire` / `Noirè`.
- Lattafa (1): `Ajwad Pink To Pink` / `Ajwad Pink to Pink`.
- Khadlaj (1): `Sueño` / `Sueno`.

These are registry-label normalization collisions, not 18 confirmed duplicate
catalog product rows: the current product catalog itself has no duplicate
normalized brand + canonical-name identities. Some pairs may be legitimate
orthographic variants, but they should be represented as one canonical
registry row with aliases where they denote the same fragrance. Do not apply
blind deletion or merge them without checking the official product identity.

**Action:** keep the new uniqueness test strict for product identities and
exact duplicate registry rows; treat normalized registry-label collisions as
a separate cleanup queue with source-by-source review before enforcing a
normalized registry uniqueness assertion.

## Branch dependency map — important integration clarification

Two of the current PRs are cumulative descendants of other catalog branches, not independent snapshots:

- **PR #555** targets `catalog/gulf-orchid-official-new-arrivals-2026-11-08`. Comparing its head with that base gives a merge base equal to the current PR #554 head (`a990036c...`), with six commits ahead and zero behind. Therefore #555 already carries the #554 line of work as ancestry. Do not integrate #554 and #555 as two independent patches; treat #555 as the cumulative descendant and resolve the Gulf Orchid duplicates against #542 plus the Lattafa overlaps against #562.
- **PR #565** targets `catalog/lattafa-four-official-products-2026-11-08`. Comparing its head with that base gives a merge base equal to the current PR #562 head (`6e33896d...`), with five commits ahead and zero behind. Therefore #565 already carries #562 as ancestry. Do not count #562's catalog rows as a second independent addition when reviewing #565; the cross-branch overlap to reconcile is the six Lattafa identities also present in #555, plus the Armaf duplicates against #558 and #564.

This matters for integration order: the eventual candidate should select the cumulative descendant branch where appropriate, rather than replaying both parent and child PR diffs and accidentally duplicating the same rows.

### Additional exact-head CI check

- PR #555 current head: run 42520228615 — success.
- PR #564 current head: run 42523877610 — success.
- PR #568 current head: run 42525428834 — success.
- PR #565 current head: no workflow run found. The branch-specific workflow trigger gap recorded above remains unresolved.

## Required integration gate

Before any of these catalog PRs are integrated:

1. Reconcile the confirmed overlap groups above.
2. Validate the combined candidate branch, not only its component PRs.
3. Assert unique canonical identities by normalized brand + canonical name.
4. Assert unique product IDs.
5. Assert unique variant IDs.
6. Assert unique variant tuples by product ID + size + concentration.
7. Assert family-registry entries map one-to-one to canonical identities.
8. Preserve official evidence URLs and only record sizes/concentrations explicitly supported by those sources.

## Safety boundary

This audit changes documentation only. It does not change product catalog data, family registry, variants, prices, stock, offers, `main`, or production. No PR is merged or closed by this report.

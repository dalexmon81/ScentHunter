# Recovery candidate — name collision audit

## Purpose

Record name collisions that must not be resolved by punctuation stripping alone. The family registry is discovery metadata; canonical product IDs, variants and verified GTINs remain the authority for product identity.

## Family-registry collisions

The cumulative harvest contains 25 within-family collision groups when punctuation and diacritics are removed. The recovery merge removes case/whitespace-only duplicate rows, but deliberately preserves these potential identity collisions for source review:

| Family | Names to review |
|---|---|
| Paris Corner | Deux II Expressions, North Stag / Deux II Expressions North Stag |
| Paris Corner | Jardin Des Papillons / Jardin des Papillons |
| Paris Corner | Lueur D'Espoir Arena Intense / Lueur d'Espoir Arena Intense |
| Paris Corner | Lueur D'Espoir Memories of Summer / Lueur d'Espoir Memories of Summer |
| Paris Corner | Lueur D'Espoir Serene Grove / Lueur d'Espoir Serene Grove |
| Paris Corner | Lueur D'Espoir Silhouette / Lueur d'Espoir Silhouette |
| Paris Corner | Midnight Sin By Daniel Rene / Midnight Sin by Daniel René |
| Paris Corner | Ministry of Oud - Gladiators Oath / Ministry of Oud Gladiators Oath |
| Paris Corner | Ministry of Oud - Maestro's Symphony / Ministry of Oud Maestro's Symphony |
| Paris Corner | Ministry of Oud - Nile Whispers / Ministry of Oud Nile Whispers |
| Paris Corner | Ministry of Oud - Oud Beyond the Wall / Ministry of Oud Oud Beyond the Wall |
| Paris Corner | Ministry of Oud - Romance Reverie / Ministry of Oud Romance Reverie |
| Paris Corner | Noir D'Arabie / Noir d'Arabie |
| Paris Corner | Papillon Des Vents / Papillon des Vents |
| Paris Corner | Quatre IV Expressions, North Stag / Quatre IV Expressions North Stag |
| Paris Corner | Rua / RUA |
| Paris Corner | Taskeen Lactea Divina / Taskeen Lactéa Divina |
| Paris Corner | Trois III Expressions, North Stag / Trois III Expressions North Stag |
| Paris Corner | Un I Expressions, North Stag / Un I Expressions North Stag |
| Arabiyat Prestige | Nyla Vani-elle / Nyla Vani-Elle |
| Arabiyat Prestige | Noire / Noirè |
| Lattafa | Ajwad Pink To Pink / Ajwad Pink to Pink |
| Khadlaj | Sueño / Sueno |
| Paris Corner | Ministry of Oud Greatest (duplicate row spelling is identical) |
| Paris Corner | Tiramisu Speculoos (duplicate row spelling is identical) |

These are discovery-registry collisions only. Do not delete or merge canonical catalog records based on this table alone. Verify official product URLs, GTINs and variant identity before any canonical change.

## Explicit canonical-identity exception: Giorgio Armani Acqua di Giò Profondo

The product seed contains two separate canonical product IDs:

- `SH-0043` — Acqua di Gio Profondo, EDP, 75 ml and 125 ml bottle variants. Verified GTINs: `3614272865228` (75 ml) and `3614272865235` (125 ml).
- `SH-AUTO-0019` — Acqua di Giò Profondo, EDP, 100 ml refillable bottle. Verified GTIN: `3614273953849`.

The source evidence explicitly says to keep the two product IDs separate. The 100 ml refillable bottle is not to be merged into the 75/125 ml product identity. The accent-insensitive name collision is therefore intentional and protected by GTIN/variant evidence.

## Cross-PR overlaps already documented

The existing cross-PR audit in PR #567 records:
- Gulf Orchid PRs #542 and #554 duplicate Cloud 9 and Maestro.
- Velixir PRs #465 and #517 repeat 48 product/size/concentration tuples.
- Armaf PRs #564 and #565 duplicate Check Mate White Knight; #558 and #565 duplicate Odyssey French Kiss.
- Lattafa PRs #555 and #562 overlap on six canonical identities.
- Mykonos PRs #539 and #546 overlap on 14 official detail-page evidence URLs.
- Armaf PRs #569 and #573 repeat the same 21 concentration/provenance corrections.

These patches must be reconciled as one cumulative data set. Green CI on individual PRs is not proof that their combined result is unique.

## Rule

Preserve canonical product IDs and verified GTIN mappings unless source evidence proves two IDs refer to the same purchasable identity. Merge spelling/alias noise in discovery metadata only when it cannot collapse distinct concentrations, formats, refillable bottles or GTIN-backed variants.

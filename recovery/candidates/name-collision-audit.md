# Recovery candidate — name collision audit

## Purpose

Record name collisions that must not be resolved by punctuation stripping alone. The family registry is discovery metadata; canonical product IDs, variants and verified GTINs remain the authority for product identity.

## Remaining family-registry collisions

After merging the cumulative harvest, PR #425 seed and current-main exclusions, and removing case/whitespace-only duplicate rows, 16 within-family name pairs still collide when punctuation and diacritics are normalized:

| Family | Names to review |
|---|---|
| Arabiyat Prestige | Noire / Noirè |
| French Avenue | Papa Yeah / Papa Yeah! |
| Giorgio Armani | Acqua di Gio Profondo / Acqua di Giò Profondo |
| Khadlaj | Sueno / Sueño |
| Paris Corner | Deux II Expressions North Stag / Deux II Expressions, North Stag |
| Paris Corner | Midnight Sin By Daniel Rene / Midnight Sin by Daniel René |
| Paris Corner | Ministry of Oud - Gladiators Oath / Ministry of Oud Gladiators Oath |
| Paris Corner | Ministry of Oud - Maestro's Symphony / Ministry of Oud Maestro's Symphony |
| Paris Corner | Ministry of Oud - Nile Whispers / Ministry of Oud Nile Whispers |
| Paris Corner | Ministry of Oud - Oud Beyond the Wall / Ministry of Oud Oud Beyond the Wall |
| Paris Corner | Ministry of Oud - Romance Reverie / Ministry of Oud Romance Reverie |
| Paris Corner | Quatre IV Expressions North Stag / Quatre IV Expressions, North Stag |
| Paris Corner | Taskeen Lactea Divina / Taskeen Lactéa Divina |
| Paris Corner | Trois III Expressions North Stag / Trois III Expressions, North Stag |
| Paris Corner | Un I Expressions North Stag / Un I Expressions, North Stag |
| Zimaya | Elixir - White / Elixir White |

These are discovery-registry collisions only. They are deliberately retained as separate labels until official product pages, GTINs and variant identity establish whether each pair is an alias or a distinct product. Do not merge canonical catalog rows based on this table alone.

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

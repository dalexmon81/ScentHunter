# Notino canonical format-flag reconciliation — 25 November 2026

## Current database state

Read-only inspection of the operational Neon branch `br-red-night-ba3reqhp`:

- Canonical variants: **556**
- Variants with all four format flags explicitly false: **17**
- Variants with at least one unknown flag (`is_tester`, `is_refill`, `is_gift_set`, `is_mini`): **539**
- Notino store-product rows: **28,012**
- Notino store-product rows already linked to a canonical variant: **108**

The canonical matcher is intentionally strict. It does not assume that an unknown tester/refill/gift/mini flag is false. New direct Notino records without an exact GTIN or reviewed store-product mapping therefore remain pending.

## Candidate evidence set for human review

A read-only query found **19** unknown-flag variants with product titles from at least two independent stores and no obvious special-format marker (`tester`, `refill`, `recharge`, `coffret`, `gift set`, `miniature`, `mini`) in any linked title.

These are candidates for a narrowly scoped, evidence-backed backfill to explicit `false`; they have **not** been changed.

| Brand | Fragrance | Concentration | Size | Independent store titles |
|---|---|---:|---:|---|
| Armani | Sì | Eau de Parfum | 30 ml | Notino.fr; Sabina.es |
| Armani | Sì Passione | Eau de Parfum | 30 ml | Notino.fr; Sabina.es |
| Azzaro | Chrome | Eau de Toilette | 200 ml | Notino.fr; Parfumzentrum.de |
| Azzaro | The Most Wanted Eau de Toilette Intense | Eau de Toilette Intense | 50 ml | Notino.fr; Parfumzentrum.de; Sabina.es |
| Azzaro | The Most Wanted Parfum | Parfum Intense | 50 ml | Notino.fr; Sabina.es |
| Azzaro | The Most Wanted Parfum | Parfum Intense | 100 ml | Notino.fr; Parfumzentrum.de |
| Azzaro | Wanted | Eau de Toilette | 100 ml | Notino.fr; Sabina.es |
| French Avenue | Liquid Brun | Eau de Parfum | 100 ml | Bplatz; Sabina.es |
| French Avenue | Liquid Brun Limited Edition | Extrait de Parfum | 150 ml | Bplatz; Sabina.es |
| Givenchy | Gentleman Reserve Privee | Eau de Parfum | 60 ml | Notino.fr; Parfumzentrum.de |
| Guerlain | L'Homme Idéal | Eau de Toilette | 150 ml | Notino.fr; Parfumzentrum.de |
| Jean Paul Gaultier | Le Male Elixir | Parfum | 75 ml | Notino.fr; Sabina.es |
| Maison Alhambra | Jean Lowe Immortal | Eau de Parfum | 100 ml | Bplatz; Sabina.es |
| Prada | Luna Rossa Ocean | Eau de Toilette | 50 ml | Notino.fr; Sabina.es |
| Rasasi | Hawas Black | Eau de Parfum | 100 ml | Bplatz; Sabina.es |
| Rasasi | Hawas Fire | Eau de Parfum | 100 ml | Bplatz; Sabina.es |
| Rasasi | Hawas For Him | Eau de Parfum | 100 ml | Bplatz; Notino.fr |
| Rasasi | Hawas Ice | Eau de Parfum | 100 ml | Bplatz; Notino.fr |
| Versace | Eros Flame | Eau de Parfum | 50 ml | Notino.fr; Sabina.es |

## Recommendation

1. Review these 19 rows and their raw retailer titles.
2. If approved, set the four flags to explicit false only for this reviewed set, using a reversible, audited migration with before/after counts.
3. Keep the remaining 520 unknown-flag variants unresolved until equivalent evidence or exact GTIN/retailer mappings exist.
4. Do not weaken the matching algorithm or infer format flags from missing data.

This document is a candidate review report only. No Neon data was modified.

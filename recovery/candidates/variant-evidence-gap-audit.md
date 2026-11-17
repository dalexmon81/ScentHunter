# Variant evidence and concentration gaps — recovery candidate

This is an audit only. No variant fields were inferred or changed.

## Aggregate
- Variant rows: 141
- Rows with `source_evidence_url`: 53
- Rows without `source_evidence_url`: 88
- Rows with concentration: 127
- Rows with concentration blank: 14

A product-level `source_url` is not automatically proof of every variant's exact size or concentration. A variant with a recorded concentration but no variant-level evidence URL still needs a provenance review before treating that concentration as independently verified.

## By brand
| Brand | Variants | Evidence URL | Missing evidence URL | Missing concentration |
|---|---:|---:|---:|---:|
| Afnan | 3 | 0 | 3 | 0 |
| French Avenue | 14 | 0 | 14 | 12 |
| Giorgio Armani | 3 | 0 | 3 | 0 |
| Khadlaj | 26 | 0 | 26 | 1 |
| Lattafa | 4 | 0 | 4 | 1 |
| Maison Alhambra | 17 | 0 | 17 | 0 |
| Mykonos | 73 | 53 | 20 | 0 |
| Swiss Arabian | 1 | 0 | 1 | 0 |

## Variants with concentration currently blank
| Brand | Product | Variant ID | Size ml | Variant evidence URL |
|---|---|---|---:|---|
| Khadlaj | Hareem Al Sultan Gold | `SHV-SH-KHADLAJ-f492c4b4-35-000` | 35 | Not recorded |
| French Avenue | Carnal Desire | `VAR-8211a295af50619e` | 100 | Not recorded |
| French Avenue | Forbidden Fruit | `VAR-be6d95d564d87974` | 100 | Not recorded |
| French Avenue | Frostbite | `VAR-aad6950d558d4153` | 100 | Not recorded |
| French Avenue | Magnetiq | `VAR-7746a36c70542c6e` | 100 | Not recorded |
| French Avenue | Naughty Dates | `VAR-edc7ad8559f63f4a` | 100 | Not recorded |
| French Avenue | Ora | `VAR-a5e44a70c007b55f` | 100 | Not recorded |
| French Avenue | Platine Blanc | `VAR-840c7c7a6b1d47c8` | 100 | Not recorded |
| French Avenue | Royal Taboo | `VAR-9d198be4b62eabbf` | 100 | Not recorded |
| French Avenue | Roza | `VAR-0ac0dac233b48f0b` | 100 | Not recorded |
| French Avenue | Sun Kissed | `VAR-8d5cef4e1caea5a1` | 100 | Not recorded |
| French Avenue | Teas Me | `VAR-71769965f684eae0` | 100 | Not recorded |
| French Avenue | X Xandal | `VAR-ef886184af831d72` | 100 | Not recorded |
| Lattafa | Asad Elixir | `VAR-97d1b2cdcc3a8b55` | 100 | Not recorded |

## Rule
- Do not fill blank concentrations from product titles, sibling sizes, retailer guesses, or naming conventions.
- Keep unknown values blank until a direct product/variant source or an explicitly approved evidence source establishes the exact variant.
- Prioritize adding exact product-page evidence for the 88 rows without `source_evidence_url`.

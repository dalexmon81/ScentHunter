# Requested brand catalog reconciliation — 2026-11-08

## Scope

The canonical seed on `catalog/complete-brand-expansion-2026-11` is the source snapshot for this review. It contains **1,726 canonical product identities**, **192 explicit variants**, and 22 brand labels.

The requested names have been mapped to the catalog's normalized labels. The user's "Alambra" is represented as **Maison Alhambra**. Games of Spades remains represented as a collection/brand label, with Jo Milano Paris as manufacturer where provenance records say so. Aromatix remains a collaboration line associated with French Avenue rather than a false independent manufacturer.

## Existing canonical coverage

| Brand / line | Canonical identities |
|---|---:|
| Velixir | 28 |
| Mykonos | 72 |
| Maison Asrar | 120 |
| Khadlaj | 55 |
| Bujairami | 142 |
| Paris Corner | 243 |
| Assaf | 21 |
| Al Wataniah | 10 |
| Armaf | 190 |
| French Avenue | 117 |
| Arabiyat Prestige | 118 |
| Gulf Orchid | 20 |
| Swiss Arabian | 32 |
| Games of Spades | 29 |
| Lattafa | 91 |
| Afnan | 87 |
| Aromatix | 12 |
| Maison Alhambra | 203 |
| Zimaya | 72 |
| Al Haramain | 61 |

These are identities already in the reviewed branch, not a claim that every SKU, size or concentration variant sold worldwide has been captured.

## Source-led reconciliation

The seed was compared against:
- `backend/catalog_overlays/verified_fragrance_name_harvest_2026-11-08.json`
- `backend/catalog_overlays/official_brand_listing_reconciliation_2026-11-08.json`

Both overlays are discovery evidence only. Names were matched after Unicode accent and punctuation normalization against both canonical names and aliases.

**New distinct name identities missing from these two overlays: 0.**
No missing distinct identities were found.

Where a listing label is merely a collaboration display name or spelling variation for an existing identity, it should be retained as an alias and not cloned as a duplicate canonical product. Existing records are therefore not inflated by adding duplicate entries.

## Evidence limits and next harvesting work

The public sources confirm product names and some product details, but collection totals may include overlapping collections, non-perfume formats, discovery kits, sets, room/home scent, body products, or multiple variants. A collection count is not a reliable unique-perfume count.

The current source overlays do not prove an exhaustive current global range for every requested brand. Further source-led harvesting should be done brand-by-brand using paginated official fragrance-only collections and individual product pages. New names can be retained as `source_listed_name`; size/concentration variants require explicit product-page evidence. Any unresolved manufacturer/line distinction must remain explicit.

No prices, stock, availability, shipping costs, retailer offers, affiliate attributes, GTINs or inferred variants are added by this reconciliation.

## Verification checklist

- Normalize accents, punctuation, and spacing before duplicate checks.
- Compare canonical names and aliases before adding a row.
- Preserve official listing spelling as an alias when it names an existing identity.
- Preserve collection/manufacturer attribution.
- Exclude non-perfume formats from perfume identities unless modeled as a separate product type.
- Require individual evidence for size/concentration variants.
- Do not promote listing-backed records to product-detail verified status without direct evidence.
- Keep the staging Liquid Brun live-retailer test separate from this catalog seed PR.
- Keep PR #424 open and untouched.

# Al Haramain official EU catalog reconciliation — 2026-11-08

## Source scope

The official Al Haramain EU storefront currently exposes a broad collection with
198 total listings and 189 shown per page. Its listing mixes perfumes, extrait
concentrations, concentrated perfume oils, attars, travel sets and gift sets.
The official 2025–2026 e-catalog also separates perfumes, gift sets, premium
concentrated perfume oils, bukhoor, air fresheners, deodorants, agarwood and
dehnal oudh into distinct sections.

Official references:
- https://shop.alharamainperfumes.com/eu/collection.html
- https://shop.alharamainperfumes.com/eu/collection.html?gender=5785%2C5787&type=5789%2C5794
- https://shop.alharamainperfumes.com/eu/collection.html?gender=5785%2C5786&type=5788%2C5789%2C5791
- https://shop.alharamainperfumes.com/E-Catalog/e-catalog.pdf

The collection pagination currently repeats much of the same product sequence
between pages, so page-count totals must not be interpreted as unique products.
The EU storefront's page-one listing provides explicit size/concentration
evidence for the variants recorded in this update.

## Existing seed and family-registry correction

The branch already contained 37 Al Haramain canonical product rows and 36
family-registry entries. One product, `Amber Oud Gold Edition`, used the
malformed family ID `al-haramain_catalog`, so it was not included in the
`al_haramain_catalog` family. The product ID was preserved, its family ID was
corrected to `al_haramain_catalog`, and its missing family-registry entry was
added.

Final exact parity:
- Catalog products: 37
- Registry products: 37
- Catalog-only names: 0
- Registry-only names: 0
- Incorrect family IDs: 0

## Official variant evidence

Thirty existing canonical identities were matched to exact product names on
the official EU listing and upgraded to `source_verified_name`. A total of 46
explicit variants were added from the listing's displayed size and
concentration fields. Examples include:
- Amber Oud Ruby Edition: 60, 120 and 200 ml EDP
- Amber Oud Gold Edition Extreme: 60 and 100 ml Extrait de Parfum
- Amber Oud Ultra Violet: 60, 120 and 200 ml EDP
- Amber Oud Aqua Dubai: 75, 100 and 200 ml Extrait de Parfum
- Amber Oud Carbon Edition: 60, 100 and 200 ml EDP
- L'Aventure Femme: 30 and 100 ml EDP
- L'Aventure Rose: 100 and 200 ml EDP
- Azlan Oud Bleu, Saffron, Amber and Charcoal Editions: 100 ml Extrait de Parfum

Twenty-eight products with no sufficiently explicit matching size/concentration
on the inspected official listing remain unexpanded; no variant data was
guessed. In particular, oils, attars, travel sets and gift sets shown in the
official store/catalog were not converted into spray variants or inserted as
canonical spray products.

The catalog contains two similarly named rows, `Amber Oud Gold Edition
Extreme` and `Amber Oud Extreme Gold Edition`. They were not merged because
the inspected sources did not conclusively establish whether the names refer
to one identity or distinct products. This remains a manual reconciliation
candidate.

## Tests and branch totals

Added six regression tests at
`backend/tests/test_al_haramain_catalog.py` covering exact registry parity,
family IDs, official source provenance, Ruby Edition variant sizes,
exclusion of oil/gift-set records from spray variants, and ID uniqueness.

Whole branch totals after this update: 1,940 canonical products and 318
variants. No retailer offer records, live prices, stock, shipping or GTINs
were added. The source is a current EU storefront snapshot, not an exhaustive
historical or global release archive. CI must still run against the final PR
head before any merge.

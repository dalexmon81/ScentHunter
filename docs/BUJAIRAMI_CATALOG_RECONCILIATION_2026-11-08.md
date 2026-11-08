# Bujairami catalog reconciliation — 8 November 2026

## Result

The current Bujairami seed contains **671 canonical identities and 8 explicit size variants**. This is a cross-source union, not a claim that every identity is currently available for purchase.

It combines three overlapping source lists:
- 587/587 named entries in the audited A–L portion of the EU retailer's 1,223-name range index; M–Z remains to be reconciled.
- 117/117 names in the current official UAE collection.
- 38/38 perfume identities in the official Australian Originals collection.

These lists overlap and are not additive. The 671 unique product records currently use 519 EU range-index source URLs, 117 UAE collection source URLs, two EU shop source URLs and 33 individual Australian product-page source URLs.

## Confirmed variants

Eight size variants have individual evidence URLs:
- Love Spell — 50 ml and 100 ml
- Iconic — 100 ml
- Australian Tonka — 100 ml
- Happy Hour — 100 ml
- Pretty F**ked Up — 50 ml
- The F*ck Up — 50 ml
- G’Day — 100 ml

The official Australian Originals pages confirm the bottle sizes. Concentration is left unset for these variants because the cited product pages do not explicitly state EDP or Extrait.

## Direct official pages added or rechecked

- The F*ck Up — official product detail page now resolves and confirms 50 ml: https://bujairami.com.au/products/the-f-ck-up-original-creation
- G’Day — official product page confirms 100 ml: https://bujairami.com.au/products/gday-bujairami-original-niche
- Midnight in Melbourne — official product detail page confirms the name, but no bottle size is displayed: https://bujairami.com.au/products/midnight-in-melbourne-bujairami-original-niche

Other first-party size evidence is recorded on the Love Spell, Iconic, Australian Tonka, Happy Hour and Pretty F**ked Up variants.

## Naming and source-quality rules

- Names discovered through the EU retailer's A–L index remain source_listed_name unless an official product detail page verifies them.
- The 117-name UAE collection and 38-name Australian Originals collection are separate checks; overlapping names are canonicalized rather than duplicated.
- The Australian Originals collection includes a body spray; it is excluded from the perfume catalog.
- Size and concentration are not inferred from names, price, scent descriptions or collection membership.
- Two A–L names currently have only a broad EU shop listing and no product-specific evidence: Gold Coast Shiraz and Sunrise in Sydney. They remain name-only with no variants.
- The M–Z portion of the 1,223-name range index has not yet been audited. This PR must not be described as the complete worldwide Bujairami catalog.

## Validation

- 671 canonical Bujairami identities.
- 8 variants, all with source_evidence_url.
- No duplicate product IDs, canonical names, variant IDs or product-size pairs.
- No orphan variants or size mismatches.
- UAE current range: 117/117 names represented.
- Australian Originals perfume range: 38/38 names represented.
- A–L range: 587/587 names represented; M–Z pending.

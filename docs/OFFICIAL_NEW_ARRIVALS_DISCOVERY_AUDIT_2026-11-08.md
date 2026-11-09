# Official New-Arrival Discovery Audit — 2026-11-08

## Purpose and safety boundary

This is a discovery-only audit layer for the requested-brand catalog work. It records first-party collection pages that expose possible additions or variants. It does **not** authorize importing every collection card as a canonical fragrance.

No rows were added to `backend/product_catalog.json` or `backend/family_registry.json` in this audit. No existing identity was renamed, deleted, or marked discontinued. Each candidate must still be matched against the current seed by normalized brand + name, checked against an individual product page, and classified as a fragrance identity, size/concentration variant, travel edition, gift set, body product, or other non-fragrance item.

## First-party discovery sources

| Brand | Official discovery page | Discovery evidence | Required next check |
|---|---|---|---|
| Afnan | https://www.it.afnan.com/en/collections/new-arrivals | The official new-arrivals page currently exposes 9 cards, including 9 PM Night Out, 9 PM Rebel, 9 PM, Turathi Electric, Rare Reef, Lynked Forever, Lynked Freedom, 9 PM Elixir and Historic Sahara. It also displays a Supremacy gift set. | Match every scent to the existing Afnan seed; open individual product pages; exclude gift sets as identities and record travel editions as variants only when exact size evidence exists. |
| Afnan (US storefront) | https://us.afnan.com/collections/new-arrivals | The US page additionally exposes Stardust, Kiaana Vibes and Tribute Blue travel edition in its current listing. | Treat regional assortment differences as evidence, not automatic new products. Verify exact official product detail pages and size/concentration before adding. |
| Zimaya | https://us.zimayaperfumes.com/collections/new-launch-perfumes | The page displays Kibria Supremo, Kibria Glory, Oscar Platinum, Ode to Rose Royale, Ode to Rose Bella, Ghali Elegant, Ghali Imperial, Modhesh Noble, Al Embratur Absolu, Daiman Eclipse, Daiman Eden, Zukhruf Peach Please, Mazaaj Rhythm, Tiramisu S’mores and Sharaf Divine. The same page's descriptive copy refers to 23 fragrances, while the visible collection output shows 15 cards. | Do not use the page's count as a catalog count. Check individual product pages, exact brand attribution, concentration and size. Reconcile any regional product aliases before adding. |
| Swiss Arabian | https://swissarabian.com/collections/new-launches | The official collection reports 29 results. It includes Shaghaf Oud Marine and Echoes of St. Moritz, alongside collector editions, 25 ml mini products and mini gift sets. | Separate full-size canonical fragrances from minis (variants) and gift sets (not canonical fragrance identities). Verify the individual fragrance pages. |
| Swiss Arabian — launch announcement | https://at.swissarabian.com/blogs/news/swiss-arabian-unveils-two-new-perfumes-and-launches | Official 7 April 2026 announcement names Shaghaf Nectar Blush and Patchouli 01 as new creations. | Check whether both identities and exact variants already exist in the seed. Use product detail pages for size/concentration; the announcement alone is not variant evidence. |
| Bujairami | https://bujairami.com.au/collections/new-arrivals | The official new-arrivals collection reports 55 products and includes a mixture of original creations and inspired-by fragrances, with some sold-out entries. | Reconcile each item against the Bujairami seed and existing aliases. Do not create duplicates from spelling differences, inspiration text, limited-size editions or out-of-stock status. Confirm individual product page and exact concentration/size. |

## Candidate handling rules

1. **Canonical identity:** create only when the product is a distinct named fragrance attributable to the requested brand and not already represented by an existing canonical identity or alias.
2. **Variant:** add a size/concentration row only when that exact combination is explicitly supported by a product detail page or an unambiguous official variant selector.
3. **Gift set / collector set:** do not create a fragrance identity for the set. Individual fragrances inside a set may be considered only when independently identified and supported.
4. **Mini / travel size:** attach to the existing canonical identity as a variant when the named scent and exact volume are explicit. Do not assume concentration from a parent page unless the variant evidence supports it.
5. **Inspired-by wording:** retain the Bujairami fragrance's own name as the identity; never merge it with the referenced designer fragrance.
6. **Regional storefronts:** preserve the source URL used for the evidence. A product shown in one region is not proof that every size or concentration is sold in another region.
7. **Availability:** sold-out does not mean discontinued. Do not delete or deactivate an identity based only on current stock state.
8. **Provenance:** product-level `source_url` must point to the individual product page when available. Collection pages belong in audit evidence, not as a substitute for individual product provenance.

## Suggested next pass

- Compare the candidate names against all existing product names, aliases and family-registry entries.
- Retrieve the individual official product pages for candidates that are not already represented.
- Record explicit volume and concentration per variant; leave fields absent when the source does not state them.
- Add focused regression tests for confirmed identities and exact variants.
- Update catalog and family registry only after the evidence table is complete.
- Run the full catalog validation workflow and inspect its logs before proposing any merge.

## Source limitations

This document captures the visible first-party collection listings on 8 November 2026. Collection pages are dynamic and may change. Counts on a collection page may include sets, minis, body products or other non-canonical items. The audit intentionally does not claim completeness and does not infer a launch date solely from a product appearing in a current collection.

# Mykonos official detail-page evidence audit — 8 November 2026

## Scope

This change does not add new canonical Mykonos identities. The existing catalog contains 72 Mykonos identities. The brand-owned storefront's current all-products collection reports 54 product records, while its 50 ml and 100 ml collections expose size-specific listings. The EU authorized retailer separately advertises 90 catalogue entries. These counts are not interchangeable: they may reflect current listings, legacy identities, size variants, travel-size products and future/coming-soon products.

The brand-owned store is used as the primary evidence source:
- All products: https://officialmykonos.com/collections/all
- 50 ml collection: https://officialmykonos.com/collections/50ml-colection
- 100 ml collection: https://officialmykonos.com/collections/100ml-collection
- Travel-size product: https://officialmykonos.com/products/mykonos-sansa-edp-travel-size-15ml

## Detail-page upgrades

Fifteen existing identities were upgraded from collection-level evidence to individual brand-owned product pages:
- Invade
- Glitch
- Empire x RRQ
- MyEgo
- Xoxo Rosy
- Verve
- Vanilla Clouds
- Stilettos
- Sorrento
- Slow Living
- Silent Whisper
- Senja
- Royal Ispahan
- Reflection
- Reflection Elixir

For each identity, `source_url` and `source_evidence_url` now point to its individual official product page and `identity_status` is `source_verified_name`. Twenty-three existing 50 ml and 100 ml variants now carry the matching individual detail-page URL as variant-level evidence. The one 15 ml Royal Ispahan travel-size variant retains the configurable Travel Size page as its evidence. Existing variant sizes and concentrations were retained, not inferred or expanded.

## Important source distinction

The official 15 ml Travel Size page is one configurable product with a list of fragrance options. It explicitly names the 15 ml choices and has a selector for additional options. The catalog's 15 ml variant evidence should therefore be interpreted as a configurable travel-size offer, not as proof of a separate 15 ml product-detail page for each scent. The Royal Ispahan 15 ml row retains this travel-size URL rather than inheriting its 50/100 ml detail page. No new 15 ml sizes were added in this change.

## No speculative expansion

No extra identities were added from the EU retailer's 90-item catalogue or from coming-soon products. The current official collection's 54 product count does not establish that all older catalog identities are invalid; historical and current products need a separate lifecycle status before any are removed.

## Validation

The new regression test checks all 15 upgraded identity URLs, their `source_verified_name` status, and variant-level evidence URLs, including the distinct travel-size source. It does not claim that the 72-identity Mykonos set is historically complete.

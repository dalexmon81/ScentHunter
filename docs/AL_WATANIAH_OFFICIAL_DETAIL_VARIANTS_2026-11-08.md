# Al Wataniah official product-detail reconciliation — 8 November 2026

## Scope

This pass upgrades nine existing Al Wataniah catalog identities from collection-listing evidence to individual brand-owned product pages. The official store identifies Al Wataniah as a UAE perfume brand and organizes its range into Classic, Eternal, Niche, and Munchies collections. Its broad all-products collection also includes non-perfume categories such as air fresheners and perfumed body mist, so it is not imported wholesale as a fragrance list.

## Verified individual product pages and variants

All nine official pages explicitly state **Eau de Parfum, 100 ml**:

| Existing identity | Official detail page |
|---|---|
| Kayaan Classic | https://www.alwataniah.com/products/kayaan-classic |
| Kayaan Terra | https://www.alwataniah.com/products/kayaan-terra |
| Kayaan Gold | https://www.alwataniah.com/products/kayaan-gold |
| Kayaan Midnight | https://www.alwataniah.com/products/kayaan-midnight |
| Al Daiem | https://www.alwataniah.com/products/al-daiem |
| Al Daiem Elixir | https://www.alwataniah.com/products/al-daiem-elixir |
| Arya Peony Rose | https://www.alwataniah.com/products/arya-peony-rose |
| Royal Oak I | https://www.alwataniah.com/products/royal-oak-i |
| Royal Oak II | https://www.alwataniah.com/products/royal-oak-ii |

## Catalog changes

- Existing canonical product IDs are preserved.
- `source_url` and `source_evidence_url` now point to the individual official product page.
- `identity_status` is upgraded to `source_verified_name`.
- Each product now has `formats_ml: [100]` and `concentration: "Eau de Parfum"`.
- Nine explicit 100 ml EDP variants are added.
- The family registry is aligned with the verified formats and concentration.
- The existing two variants for Lemon Souffle and Choco Truffle are preserved.
- No prices, offers, stock, shipping, or availability data are imported.

## Snapshot after change

- Canonical identities: 2,074 (unchanged)
- Total variants: 341
- Al Wataniah identities: 86 (unchanged)
- Al Wataniah variants: 11

## Regression protection

The existing `backend/tests/test_al_wataniah_official_collection_harvest.py` now checks the nine official detail-page records and the total of eleven explicit product variants.

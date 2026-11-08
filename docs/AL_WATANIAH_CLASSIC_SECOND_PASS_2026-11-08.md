# Al Wataniah Classic official product variants — second pass — 8 November 2026

## Scope

This pass upgrades eight more existing Al Wataniah catalog identities to individual pages on the brand-owned Al Wataniah storefront. Each inspected page explicitly states Eau de Parfum and 100 ml.

## Verified records

| Existing identity | Official page | Verified format |
|---|---|---|
| Rose Mystery Intense | https://www.alwataniah.com/products/rose-mystery-intense | 100 ml Eau de Parfum |
| Nawal Tanzanite | https://www.alwataniah.com/products/nawal-tanzanite | 100 ml Eau de Parfum |
| Durrat Al Aroos | https://www.alwataniah.com/products/durrat-al-aroos | 100 ml Eau de Parfum |
| Ameeri | https://www.alwataniah.com/products/ameeri | 100 ml Eau de Parfum |
| Sabah Al Ward Garden of Eden | https://www.alwataniah.com/products/sabah-al-ward-garden-of-eden | 100 ml Eau de Parfum |
| Al Layl | https://www.alwataniah.com/products/al-layl | 100 ml Eau de Parfum |
| Ameerati | https://www.alwataniah.com/products/ameerati | 100 ml Eau de Parfum |
| Sultan Al Lail | https://www.alwataniah.com/products/sultan-al-lail | 100 ml Eau de Parfum |

## Catalog changes

- Existing canonical product IDs are preserved.
- Individual official pages replace collection-listing URLs in `source_url` and `source_evidence_url`.
- All eight records are marked `source_verified_name`.
- Each receives `formats_ml: [100]`, concentration `Eau de Parfum`, and one matching 100 ml variant.
- The Al Wataniah family registry is aligned.
- No prices, offers, stock, shipping, or availability are imported.

## Snapshot after this pass

- Canonical identities: 2,074 (unchanged)
- Total variants: 357
- Al Wataniah identities: 86 (unchanged)
- Al Wataniah variants: 27

## Regression protection

The existing `backend/tests/test_al_wataniah_official_collection_harvest.py` is extended to validate these eight additional official product pages and variants.

# Paris Corner catalog audit — 2026-11-08

## Verified current-store additions

The official Paris Corner UAE store lists 268 items across several product types, including EDP, Extrait, gift sets, body mist, travel sizes and perfume oils. It groups multiple sub-lines under the Paris Corner umbrella (Valar Series, Arabian Oryx, Autobiography, Pendora Scents, Factory Edition, Emir and Magic Oud).

A comparison against the existing 246 Paris Corner identities found **27 additional perfume identities** on official product pages that were absent from the seed. This update adds those 27 products and creates one explicit size variant for each:
- 20 × 100 ml EDP
- 4 × 65 ml EDP (Autobiography)
- 1 × 75 ml EDP (Cedrat Essence)
- 2 × 100 ml EDP (Arabian Oryx included in the 20 count)

No body mist, perfume oil, gift set or travel-size listing has been promoted to a separate perfume identity in this change.

## Validation

- Paris Corner identities increased from 246 to 273.
- 27 new individual official product pages.
- 27 explicit EDP variants.
- Each row includes collection/sub-line attribution.
- Regression test checks source URL, concentration and size for all 27 additions.

## Remaining reconciliation

The Paris Corner family registry contains additional names not yet represented as catalog products. Some are spelling aliases or canonical-name variants; others are historical or sub-line products (including Ministry of Oud, North Stag and other collections). These require separate source-by-source review. This PR does **not** claim Paris Corner is fully complete.

The official store's 268-item count is a SKU/product count across multiple product types, not a count of 268 unique perfume identities. The Fragrantica count is a separate historical database count and is not directly comparable.

## Sources

- Official Paris Corner UAE store collection: https://ae.pariscorner.com/collections/all
- Individual product pages are recorded in backend/product_catalog.json.
- Fragrantica Paris Corner designer index: https://www.fragrantica.com/designers/Paris-Corner.html

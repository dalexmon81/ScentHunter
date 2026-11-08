# Gulf Orchid official collection audit — 2026-11-08

## Scope

Reconcile the Gulf Orchid entries in the catalog against the official Gulf Orchid shop collection and keep canonical product identities separate from collection names and other product categories.

Official sources consulted:

- Gulf Orchid perfume collection: https://shop-gulforchid.com/collections/gulf-orchid-perfume
- Official shop product/category navigation: https://shop-gulforchid.com/products
- Official corporate portfolio: https://gulforchid.com/portfolio/gulf-orchid/

The official shop navigation distinguishes Perfume from Body Mist, Hair Mist, Deodorant, Room Spray, Reed Diffuser, Mukhammaria, Body Lotion and gifting/bundle categories. A collection title alone is not sufficient evidence for a canonical perfume identity.

## Catalog corrections

The previous catalog contained 23 Gulf Orchid records. The audit retains 13 individually named perfume listings and removes 10 records that were not valid Gulf Orchid perfume identities:

- Eight names were present only as collection labels in the general collections index: Al Qasr, Asala, Hamsat, Hikma, Jawhara, Jewel, Riwaya and Turath. They are not promoted as individual perfumes without product-level evidence.
- Vanilla Aura and Vanilla Voyage were attributed to Gulf Orchid even though the official Gulf Orchid perfume collection labels those listings as Maison Asrar. Both already exist under Maison Asrar in the catalog, so the duplicate Gulf Orchid rows were removed rather than creating new identities.

The 13 retained Gulf Orchid names are:

- Vanilla Addiction
- Mango Ice
- Cotton Candy Musk
- Tahara Vanilla Musk
- Sweet Heaven 20ML
- Pink Marshmallow
- Coco Blanco
- Exotic Oud
- Vanilla Latte
- Cookie Bite
- Sweet Like Candy
- Sweet Heaven Extreme 20ML
- Piña Colada Musk

## Data quality decisions

- The catalog contains 13 Gulf Orchid canonical identities after reconciliation.
- Exact official product URLs are retained where available. Three names are currently evidenced through the official filtered collection page.
- No concentration or size variants were added by inference. In particular, the text "20ML" in a listing name is not used to fabricate a separate variant record.
- No prices, stock states, availability claims or retailer offers were imported.
- No unrelated product categories (body mist, hair mist, deodorant, room spray, reed diffuser, body lotion, mukhammaria or gift bundles) were added as perfume identities.

## Validation

The dedicated regression test checks the exact retained name set, source URLs, identity status, absence of invented concentration/format data, removal of collection-only labels, correction of Maison Asrar attribution and duplicate-name prevention.

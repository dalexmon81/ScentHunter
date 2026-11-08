# Al Wataniah launching-soon identities — 8 November 2026

## Scope

The official Al Wataniah homepage currently displays 12 fragrance names under its **Launching Soon** section. These names were already present in `backend/family_registry.json` but were absent from the canonical product seed.

This change promotes the names into the catalog as source-listed identities only. The homepage does not provide individual product detail pages, bottle sizes, or concentrations for these teasers.

## Added identities

- The Crest
- Onyx
- Polo Estate Navy Gold
- Kayaan Extrait
- Everest
- Emerald Plume
- Emerald Ascot
- Attar Al Wesal Ice Blue
- Sabah Al Ward Pearl
- Attar Al Wesal Intense
- Blush Papillon
- Cashmere Ivory

Official evidence:
https://www.alwataniah.com/

## Catalog handling

Each record:
- uses the existing `al_wataniah_catalog` family;
- has `identity_status: source_listed_name`;
- points to the official homepage in `source_url` and `source_evidence_url`;
- is labeled `collection_name: Launching Soon`;
- deliberately has no `formats_ml`, concentration, or variant.

No individual detail page was found for these 12 teasers in the current official homepage evidence. No sizes, concentrations, prices, offers, stock, or availability have been inferred. These are not represented as currently purchasable variants.

## Snapshot after change

- Al Wataniah canonical identities: 98
- Existing explicit product-detail variants: 2 (unchanged)
- New identities added: 12
- New variants added: 0

## Regression protection

`backend/tests/test_al_wataniah_official_collection_harvest.py` now checks all 98 family identities, including the 12 Launching Soon names, and confirms that only the two products with explicit detail-page evidence retain variants.

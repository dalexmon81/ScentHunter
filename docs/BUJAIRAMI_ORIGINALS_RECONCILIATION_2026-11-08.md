# Bujairami original-creation reconciliation — 2026-11-08

## Scope and method

Reconciled the Bujairami entries in `backend/product_catalog.json` against the official Bujairami Originals collection:
https://bujairami.com.au/collections/originals

The collection currently exposes 35 products. The catalog pass deliberately did not treat the 1,262-item all-products collection as 1,262 perfume identities: that mixed listing includes inspired-by scents, body sprays and other formats.

## Changes

Added 21 missing canonical identities:
- 20 identities backed by individual official product-detail pages (`source_verified_name`).
- The F*ck Up is retained as `source_listed_name` because the official collection entry was visible but its detail page could not be independently retrieved during this pass.

The new identities are: Australian Watermelon, Top Life, Luxe Noir, Snow White, Down Under, HIM, Gold Coast, Coco Dream, Riverina, Aussie Glow, Madeira Cake, Apple Crumble, Knefeh, Love Spell, King Street, The F*ck Up, Harbour Tea, Queens Avenue, Pistachio Cake, Woolloomooloo, and Cherry Cherry Lady.

The product identity Gold Coast is kept separate from the existing Gold Coast Shiraz. No body spray was added as a perfume identity.

## Variants

Love Spell has two explicit official size variants:
- 50 ml — https://bujairami.com.au/products/love-spell-original-creation-50ml
- 100 ml — https://bujairami.com.au/products/love-spell-original-creation

Both variants carry source URLs. No prices, stock, shipping, retailer offers or GTINs were imported.

## Snapshot after reconciliation

- Total canonical identities: 1,719
- Total explicit variants: 143
- Bujairami canonical identities: 142
- Source-confidence totals: 62 detail-page verified names; 1,657 collection/listing-backed names.

## Validation

Added `backend/tests/test_bujairami_originals.py` to assert the 21 identities, evidence-status distinction, and Love Spell size variants. The catalog validation workflow was updated to include this test. The workflow must still be considered pending until GitHub Actions reports a completed run.

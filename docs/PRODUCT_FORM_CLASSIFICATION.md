# Sellable product-form classification

## Purpose

A fragrance name is not enough to establish that two retailer listings are comparable. The same scent name may appear on a fine-fragrance bottle, perfume oil, deodorant, body mist, hair mist, body-care item, home fragrance, or set.

ScentHunter now has a controlled `product_form` field on the **sellable variant**. It is not a substitute for concentration, size, tester/refill flags, or the canonical fragrance identity.

## Controlled values

| Value | Meaning |
|---|---|
| `fine_fragrance` | Standalone fine fragrance, including explicitly identified EDP, EDT, EDC, parfum or extrait |
| `perfume_oil` | Perfume oil, attar or mukhallat |
| `deodorant` | Deodorant or antiperspirant |
| `body_mist` | Body mist, body spray or body splash |
| `hair_mist` | Hair mist |
| `body_care` | Shower gel, body lotion, body cream, hand cream and related care products |
| `home_fragrance` | Room spray, home fragrance, reed diffuser, diffuser or scented candle |
| `gift_set` | Gift set or coffret |
| `discovery_set` | Discovery set or discovery kit |

Unknown is represented by SQL/JSON `null`. Do not default an unclassified item to `fine_fragrance`.

## Evidence and assignment policy

1. Prefer a product detail page or structured retailer field that explicitly identifies the form.
2. The offer normalizer recognizes only explicit, high-confidence product-type phrases. Generic terms such as "beauty", "spray" alone, "perfume" alone, or "set" alone do not classify a form.
3. A variant's form is never inferred from a sibling variant, another concentration, a product name alone, or a shared barcode.
4. Existing variants remain `null` until reviewed. This migration intentionally performs no mass backfill.
5. `is_gift_set` remains available for the existing bundle/tester constraint; `product_form` provides the broader comparable-item category.

## Matching policy

- If both offer and canonical variant have forms, they must match exactly.
- An explicit non-fine-fragrance offer cannot match a canonical variant whose form is unknown.
- A canonical non-fine-fragrance variant cannot be matched when the offer form is unknown.
- Legacy fine-fragrance matching remains compatible when no contradictory form evidence exists.
- The same checks apply to ordinary name/size matching and the reviewed-GTIN fast path.
- A mismatch is unresolved; the matcher does not automatically merge, delete, or rewrite identities.

This is deliberately conservative. It is better to show no match than to compare an EDP price with a deodorant price.

## Initial classified seed

Only eight variants with individually reviewed EDP evidence are classified in this change:
- Maison Alhambra: Afro Leather, Alpine Homme Sport, Anarch, Anchor Black, Athena, Aura D'Eclat.
- French Avenue Genesis: Aries, Aquarius.

Each is marked `fine_fragrance` at the variant level. The remaining catalog variants stay unclassified pending their own evidence.

## Database

The Alembic migration `0004_variant_product_form` adds nullable `product_variants.product_form`, a controlled-value check constraint and an index. Existing rows are not rewritten. The migration supports SQLite batch alteration and is intended to be applied through the normal migration process; this PR does not deploy it to any environment.

# Product-form classification contract — 8 November 2026

## Purpose

The canonical product record may carry an optional `product_form`. It describes what kind of sellable product the identity represents. It is independent of concentration (EDP, EDT, Extrait), size, and variant identity.

Allowed values:

- `fine_fragrance`: conventional fine-fragrance product; concentration remains a separate field.
- `perfume_oil`: perfume oil / attar explicitly identified as oil.
- `deodorant`: deodorant or perfumed deodorant.
- `body_mist`: body mist.
- `hair_mist`: hair fragrance mist.
- `body_care`: lotion, shower gel, and other body-care products.
- `home_fragrance`: room fragrance, room spray, diffuser, or similar home scent.
- `gift_set`: gift bundle containing multiple products.
- `discovery_set`: sample or discovery assortment.
- `unknown`: legacy or insufficiently evidenced records.

## Safety rules

1. Missing `product_form` is read as `unknown` for backwards compatibility.
2. New explicit values must belong to the enum; unsupported values fail catalog loading rather than being silently accepted.
3. Never infer a form from brand, product name, concentration, volume, or barcode alone.
4. Classify only from direct product-page or equivalent reliable evidence.
5. Do not merge unlike forms into one canonical identity. A deodorant barcode must never be attached to a perfume identity.
6. Product form does not assert alcohol content and does not replace concentration or variant size.
7. This schema change does not bulk-classify the existing catalog. Unknown remains the honest value until evidence is audited.

## Implementation scope

The isolated next-engine domain model, read-only catalog adapter, and structural preflight expose and validate this field. No production API, retailer scraper, offer matcher behavior, or existing catalog row is changed by this schema-only step.

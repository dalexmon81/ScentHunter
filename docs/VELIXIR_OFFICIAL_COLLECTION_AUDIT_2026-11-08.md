# Velixir official collection audit — 8 November 2026

## Scope and primary sources

Reviewed the brand's current official storefront collection pages:

- All products: https://velixirparfums.store/collections/all
- Eau de Parfum: https://velixirparfums.store/collections/velixir-eau-de-parfum
- Extrait de Parfum: https://velixirparfums.store/collections/velixir-extrait-de-parfum
- Brand authenticity statement: https://velixirparfums.store/pages/authenticity

The authenticity page identifies the storefront as Velixir Parfums' official website. Collection listings show product names and concentration groupings.

## Reconciliation

The EDP collection shows 25 listings. One is the JTC Bundle, leaving 24 individual perfume identities.

The Extrait collection shows 5 listings. One is Sacred Four Bundle, leaving four individual perfume identities.

The canonical catalog currently contains exactly these 28 identities:
- 24 Eau de Parfum: Adonis, Aphrodite, Apollo, Ares, Artemis, Asteria, Athena, Concordia, Demeter, Galatea, Harmonia, Helios, Hera, Himeros, Icarus, Morpheus, Narcisus, Nyx, Orion, Paladin, Persephone, Poseidon, Selene, Uranus.
- 4 Extrait de Parfum: Comus, Ether, Orpheus, Panacea.

## Decision

No new canonical perfume identity is added in this pass: the current catalog already matches the individual perfumes in both official collections.

The JTC Bundle and Sacred Four Bundle are deliberately excluded as bundles, not standalone perfumes. This prevents collection merchandising from inflating perfume identity counts.

## Variant and commercial-data restraint

Collection cards show size selectors for 100 ml, 35 ml, 3 ml and 2 ml on the inspected listings. This audit does not create variant rows from a collection-level selector alone. Each individual product's purchasable size options must be checked on its own product detail page before recording explicit variants.

No prices, stock, availability or retailer offers are imported.

## Automated regression

`backend/tests/test_velixir_official_collection_audit.py` protects:
- the exact 24 EDP and four Extrait identity sets;
- exclusion of the two bundles;
- unique Velixir product IDs.

This is a collection reconciliation, not a claim that every historic/discontinued Velixir release has been found.

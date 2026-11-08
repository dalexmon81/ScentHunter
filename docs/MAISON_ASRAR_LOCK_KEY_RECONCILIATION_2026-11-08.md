# Maison Asrar Lock & Key reconciliation — 2026-11-08

## Verified additions and corrections

The branch's existing seed already contained three discovery-only Maison Asrar
identities: Plot Twist, Love Key and Unsolved Mystery. The Gulf Orchid
Maison Asrar Lock & Key collection and individual product pages explicitly
confirm each as a 100 ml Eau de Parfum:
- Plot Twist: https://shop-gulforchid.com/products/plot-twist
- Love Key: https://shop-gulforchid.com/products/love-key
- Unsolved Mystery: https://shop-gulforchid.com/products/unsolved-mystery

The canonical product IDs were preserved. Their source URLs were upgraded to
the exact product pages, identity status was promoted to
`source_verified_name`, and one 100 ml Eau de Parfum variant was added for
each. No GTIN/UPC was inferred.

## Duplicate-label correction

Two seed candidates were not distinct product identities:
- `Black Grapefruit` links to the official Maison Asrar product page titled
  `BLACK`; it is now an alias of canonical `Black`.
- `Bloom` links to the official Maison Asrar product page titled
  `BLOOM BLOOM`; it is now an alias of canonical `Bloom Bloom`.

The two erroneous duplicate canonical rows were removed. Existing canonical
IDs for Black and Bloom Bloom were preserved.

## Family registry integrity

The three Lock & Key products had a malformed family reference
`maison-asrar_catalog`; these were corrected to
`maison_asrar_catalog`. The three identities and 100 ml formats were added
to the family registry.

A full exact-name parity check now reports:
- Catalog Maison Asrar products: 119
- Registry Maison Asrar products: 119
- Catalog-only identities: 0
- Registry-only identities: 0
- Incorrect Maison Asrar family IDs: 0

A focused regression suite was added at
`backend/tests/test_maison_asrar_lock_and_key.py` with five test methods.
CI still must run against the final PR head. The total branch catalog is now
1,941 canonical products and 270 variants. The product count fell by two
because two duplicate candidates were corrected, while three explicit
variants were added.

# Family-registry identity normalization — 10 November 2026

This cumulative branch incorporates the family-registry deduplication delta from the open #672 work branch, reconciled onto the latest catalog branch without copying stale product-catalog changes.

- Removes 24 duplicate family-registry rows that normalize to an existing canonical product identity.
- Uses canonical spelling from product_catalog.json.
- Preserves former spellings and brand-prefixed forms as aliases.
- Keeps all product identities, variants, GTINs and sources unchanged.
- Reconciles the newer Paris Corner and Armaf size updates onto the deduplicated registry.

Validation on the assembled files:
- Zero normalized duplicate names within any family.
- Every catalog product with a registered family maps to exactly one normalized family row.
- All existing product IDs and variant IDs are preserved.

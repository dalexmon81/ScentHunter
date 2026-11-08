# Arabiyat Prestige follow-up reconciliation — 2026-11-08

## Fresh official-store observation

A fresh live read of the MyPerfumes Europe Arabiyat storefront and its
"New Collection" page surfaced additional Arabiyat Prestige product cards
beyond the 20 records covered by
`backend/tests/test_arabiyat_prestige_official_store.py`.

Official sources:
- https://eu.myperfumes.ae/en-de
- https://eu.myperfumes.ae/en-de/collections/new-collection

Additional names visible in the current official storefront snapshot include:
- Marwa Extrait De Parfum — 60 ml
- Bahiya Garnet — EDP 100 ml
- Nyla Vani-elle — EDP 80 ml
- Swar Venin — EDP 100 ml
- Marwa — EDP 100 ml
- Noiré Absolu — EDP 100 ml
- Noiré — EDP 100 ml

The official page also shows Mahd Al Dhahab EDP 100 ml and Mahd Al Dhahab
Extrait 60 ml as separate presentations, consistent with keeping the EDP
and Extrait identities/variants distinct where the source explicitly names
them.

## Interpretation

These are **reconciliation candidates**, not an assertion that they are
missing from the current catalog. Before importing anything, compare each
normalized name against the exact current branch seed and family registry,
including aliases and existing IDs. If a name already exists, attach the
official product-detail evidence and only add a variant when the product
detail explicitly establishes its size/concentration. If absent, verify the
individual product detail page and registry parity before adding it.

Do not import homepage prices, stock labels, or other merchandising
metadata as retailer offers. This is a catalog-identity and variant audit
only. No canonical seed, registry, offers, production data, or configuration
was changed by this note.

## Required next checks

1. Resolve all seven candidate names against the current branch's
   `product_catalog.json` and `family_registry.json`.
2. Follow the official product-detail URLs for each candidate and record
   exact source title, size and concentration.
3. Add only genuinely missing canonical identities; preserve existing IDs
   and merge spelling variants as aliases.
4. Extend regression tests to cover each verified identity and variant.
5. Run CI against the exact updated PR head and record a real Actions result.

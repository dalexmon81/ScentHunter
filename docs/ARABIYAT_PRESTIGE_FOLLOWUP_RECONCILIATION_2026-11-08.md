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


## Reconciliation against the current family registry

A direct read of `backend/family_registry.json` on this branch confirms that
six of the seven names in the earlier candidate list are already represented
in `arabiyat_prestige_catalog`:

- Bahiya Garnet
- Nyla Vani-elle
- Swar Venin
- Marwa
- Noirè Absolu
- Noire

The storefront spells the last two with an acute accent (`Noiré` and
`Noiré Absolu`), while the registry uses `Noire` and `Noirè Absolu`.
Treat this as a spelling/alias reconciliation, not as evidence for two new
identities. The family registry is discovery knowledge only; this check does
not prove that the matching canonical product and variant rows exist in
`product_catalog.json`.

## Marwa Extrait — detail page now verified

The official product detail page is:
https://eu.myperfumes.ae/en-de/collections/arabiyat-prestige/products/marwa-extrait

It explicitly identifies `Marwa Extrait De Parfum | 60ML | Unisex`, describes
it as the Marwa signature elevated into an extrait, and displays UPC
`6295156402103`. This is stronger evidence than the collection card alone.
The existing Marwa EDP 100 ml listing and the Marwa Extrait 60 ml listing
must not be collapsed into the same variant: the official page explicitly
distinguishes the extrait presentation and concentration.

The product catalog seed is too large for the current GitHub file-read
response (the connector returned an empty content body for that file). For
that reason, no canonical record or variant has been inserted and no claim is
made that it is absent from the seed. The next write must first obtain a
reliable exact catalog diff or run a repository-side script against the
branch file, then add the Marwa Extrait canonical identity/60 ml Extrait
variant only if missing, with UPC as source evidence. Preserve the existing
Marwa EDP identity and ID.

## Status correction

The previous seven-name list was overbroad: six names are already present in
the family registry. Only Marwa Extrait is a newly verified registry/catalog
reconciliation candidate from this pass. No canonical seed, family registry,
offers, prices, stock, or GTIN fields were changed in this update.


## Canonical seed reconciliation completed — Marwa Extrait

The oversized catalog blob was retrieved directly by its Git blob SHA and
parsed successfully. Before the write, it contained 1,942 canonical products
and 266 variants. Exact comparison confirmed:
- `Marwa` already existed as its own Arabiyat Prestige identity.
- `Marwa Extrait` did not exist as a canonical identity.
- The UPC `6295156402103` was not already mapped in the verified GTIN registry.

The branch now contains one new canonical identity and one explicit variant:
- Product: `SH-ARABIYAT-PRESTIGE-MARWA-EXTRAIT-6295156402103`
- Variant: `SHV-SH-ARABIYAT-PRESTIGE-MARWA-EXTRAIT-6295156402103-60-000`
- Format: 60 ml Extrait de Parfum
- Verified GTIN-13/UPC: `6295156402103`
- Evidence: official product-detail URL above

The family registry now includes the new identity and 60 ml format. The
verified GTIN-to-variant map points the UPC to this exact variant. A focused
regression test was added at
`backend/tests/test_arabiyat_prestige_marwa_extrait.py`, covering identity
uniqueness, separation from Marwa EDP, registry parity and exact GTIN mapping.

Expected branch totals after this addition: 1,943 canonical products and
267 variants. These are counts of records in this branch seed, not a claim of
complete worldwide fragrance coverage. CI still needs to execute against the
new PR head.

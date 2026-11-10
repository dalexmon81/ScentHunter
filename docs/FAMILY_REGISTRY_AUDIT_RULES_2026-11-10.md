# Family registry baseline for catalog continuation

This document accompanies the catalog continuation branch created from PR #705 head `f19cf080fe6feb785e95241176776de78027e659`.

Before changing `family_registry.json`, preserve these rules:
- One family registry ID per family.
- Every canonical catalog product must map to exactly one registry family and one canonical family product row (including a documented alias only when appropriate).
- No normalized duplicate canonical names within a family.
- Family `formats_ml` must reflect only source-backed product/variant sizes.
- Do not add speculative formats based on URL slugs, retailer listings, or a neighboring product.
- Do not change a canonical product ID to repair a registry mismatch.

The #705 source snapshot was checked independently: 34 families, zero duplicate family IDs, zero products without family rows, zero product-to-family canonical mapping gaps, and zero variants whose sizes are outside the parent product's declared formats.

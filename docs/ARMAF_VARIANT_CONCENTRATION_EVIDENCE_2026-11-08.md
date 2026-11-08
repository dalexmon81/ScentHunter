# Armaf Club de Nuit — variant concentration evidence (2026-11-08)

This change fills 21 previously blank concentration fields across five existing
Armaf Club de Nuit product identities. No product identities or variants were
added or removed. The official Armaf product pages explicitly identify these
products as Eau de Parfum and list the sizes below.

| Canonical product | Sizes in catalog (ml) | Official source |
|---|---:|---|
| Club de Nuit Untold | 10, 30, 105, 200 | https://armaf.com/products/armaf-club-de-nuit-untold |
| Club de Nuit Sillage | 10, 30, 105, 250 | https://armaf.com/products/armaf-club-de-nuit-silage-men |
| Club de Nuit Woman | 10, 30, 105, 200, 250 | https://armaf.com/products/club-de-nuit-w |
| Club de Nuit Urban Man Elixir | 10, 30, 105, 250 | https://armaf.com/products/club-de-nuit-urban-elixir-100ml |
| Club de Nuit Iconic | 10, 30, 105, 200 | https://armaf.com/products/club-de-nuit-blue-iconic-200ml |

## Rules applied

- Concentration is recorded as the catalog's normalized label Eau de Parfum.
- The official product detail page is retained as the source URL on each
  corresponding product and variant.
- No concentration is inferred from product naming, adjacent variants, or a
  third-party retailer.
- No other Armaf variants are changed in this patch.

## Validation

backend/tests/test_armaf_variant_concentration_evidence.py checks the five
product identities, exact size sets, official source URLs, and concentration
for all 21 variants.

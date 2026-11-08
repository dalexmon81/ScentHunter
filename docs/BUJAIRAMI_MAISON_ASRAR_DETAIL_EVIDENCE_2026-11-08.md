# Official detail evidence reconciliation — Bujairami and Maison Asrar

## Scope
This PR continues the catalog evidence audit on top of PR #551. It does not add canonical identities and does not alter existing product IDs.

## Bujairami
Four existing identities now point to individual official Bujairami product pages:
- Gold Coast Shiraz — https://bujairami.eu/product/gold-coast-shiraz/ — 100 ml Eau de Parfum
- G’Day — https://bujairami.eu/product/gday/ — 100 ml Extrait de Parfum
- Midnight in Melbourne — https://bujairami.eu/product/midnight-in-melbourne/ — 100 ml Eau de Parfum
- Sunrise in Sydney — https://bujairami.eu/product/sunrise-in-sydney/ — 100 ml Eau de Parfum

Each receives one explicit 100 ml variant with source URL provenance. Concentration and size are taken from the official home/product pages, not inferred from naming.

## Maison Asrar
The existing Ameer identity is upgraded from a collection-level listing to its individual official page:
https://maisonasrar.com/products/ameer

The official page establishes the individual product identity. The extracted official detail did not expose a verifiable concentration or size, so no format or variant is added.

## Catalog impact
- Canonical identities unchanged.
- Four new Bujairami variants.
- One existing Maison Asrar product source upgraded.
- No prices, stock, availability, shipping or merchant offers added.

## Validation
A new regression test checks the official URLs, identity status, exact sizes/concentrations, variant evidence, uniqueness of IDs and absence of commercial fields. The test is added to the catalog seed validation workflow.

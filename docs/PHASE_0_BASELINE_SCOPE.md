# Phase 0 baseline scope

## Active retailers

The operational Phase 0 baseline covers exactly these nine retailers:

- bplatz
- deloox
- easycosmetic
- notino
- orioudh
- parfumcity
- parfumzentrum
- perfumemarket
- sabina

Every active retailer must contribute at least one persisted offer row. The
exporter and quality workflow fail closed if any active retailer is missing or
has zero offers. A row with zero offers is never used to make coverage appear
complete.

## Temporarily excluded retailers

- amazon_de
- amazon_fr

Both Amazon marketplaces are temporarily excluded because the project does
not have the required approved Creators API credentials and marketplace
associate tags. Their scraper/configuration code is retained for possible
future reactivation. They are not counted as active retailers and must not
appear in the nine-retailer baseline CSV.

The CSV declares this scope on every offer row through `baseline_scope` and
`excluded_stores`.

## Notino source policy

Notino.fr first uses the authorized CJ/VIV XML feed when its credentials are
configured. If the feed is unavailable, catalog discovery may use ordinary
public Notino.fr navigation pages and product-page requests. Public requests
must succeed normally and return verifiable product identity, price, currency,
availability and size evidence. HTTP 403/429, challenge pages, timeouts or
incomplete parses are failures; the integration must not bypass access
controls or invent offers. The quality gate requires actual persisted Notino
offers before the baseline can pass.

## CSV grain and quality

The baseline is one row per distinct retailer offer, retaining canonical
product and variant matches where evidence supports them. It includes the
retailer, canonical product/variant IDs, fragrance identity, concentration,
size, GTIN, retailer product ID, offer URL, price, currency, availability,
capture time, source, match confidence/status and offer-validity flag.

The quality workflow checks the exact nine-store scope, non-empty offers for
every active retailer, the offer-level schema, HTTPS offer URLs, declared
Amazon exclusions and duplicate offer keys. It does not accept an aggregate
store-only CSV.

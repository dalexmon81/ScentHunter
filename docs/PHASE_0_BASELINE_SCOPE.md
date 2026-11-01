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

The report includes one operational status row for every active retailer.
Only rows with a populated source count as persisted offers; zero-offer status
rows are never counted as offers. The report must show zero counts explicitly
rather than hide retailers with no indexed data. Notino must contribute at
least one real offer for the current feed/discovery acceptance gate.

## Store scope

Only the nine retailers listed above are part of Phase 0. Amazon DE and Amazon
FR have been removed from the operational store registry, scraper adapters,
catalog discovery, refresh and resynchronization jobs, baseline worker and
smoke worker. They are not scheduled or checked as required retailers.

The baseline CSV must contain rows from exactly these nine retailers and no
other store keys.

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

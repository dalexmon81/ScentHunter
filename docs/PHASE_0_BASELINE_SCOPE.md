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

Notino.fr uses the authorized CJ/VIV XML feed. The feed is downloaded and
validated on temporary storage before its offers and sync state are published
in one catalog transaction. A malformed feed or a drop of more than 10% from
the previous successful import fails closed without replacing published data.
Feed failures do not fall back to public discovery. The quality gate requires
actual persisted Notino offers before the baseline can pass.
Search retains a CJ click URL only for an allowlisted HTTPS click host and
path whose single destination matches the stored Notino.fr product. The
destination may carry standard UTM parameters, but not other query parameters
or ambiguous paths; otherwise search uses the direct product URL. Catalog
identity remains the direct Notino URL.

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

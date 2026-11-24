# Services layer

**Responsibility:** application-level use cases and orchestration that coordinate domain packages, repositories and workers. This is a transitional layer, not a second home for catalog, matching, offer, pricing or monitoring rules.

**Domain ownership already extracted**
- `app.catalog.normalization` — canonical identity normalization.
- `app.matching.canonical_matching` — canonical variant resolution.
- `app.offers.ingestion` and `app.offers.persistence` — retailer-record ingestion orchestration and offer lifecycle persistence.
- `app.pricing.offer_refresh` — existing-offer price/availability refresh and history.
- `app.monitoring.connector_health` — connector health and quarantine transitions.

The former `services` module paths for those components are compatibility re-exports only. Do not add new business logic to those shim files.

**Remaining services** such as `connector_health` compatibility, `ingestion_run`, search and retailer orchestration must be mapped before they are moved. Keep cross-package use cases here until a destination and contract are explicit.

**Rules:** no retailer network I/O from API requests; no duplicated canonical logic; no direct schema/data changes during the structural migration; preserve caller-owned SQLAlchemy transactions.

# Catalog

**Responsibility:** canonical perfume identity and domain rules: brand aliases, fragrance-name normalization, concentration, size, sellable-format flags and stable variant identity keys.

**Implementation ownership**
- `app.catalog.normalization`: the single implementation of normalization and canonical identity helpers.
- `app.models.catalog`: SQLAlchemy persistence entities for brands, fragrances, variants and catalog-related records. ORM models remain in `app.models`; this package does not create a parallel domain database.
- `app.models.normalization`: temporary backward-compatible re-export only. New imports must use `app.catalog.normalization`.

**Boundaries**
- No retailer HTTP requests, scraping, scheduling or offer publication.
- Matching decisions belong to `app.matching` / the existing canonical matching service.
- Database reads and writes use existing repositories and persistence services.
- Regression tests live in `backend/tests`, the canonical test-discovery root.

**Migration rule:** move callers to the canonical module before removing the compatibility re-export. Never copy normalization logic into another package.

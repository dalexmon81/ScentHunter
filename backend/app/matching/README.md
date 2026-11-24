# Matching layer

**Responsibility:** resolve retailer product observations to one canonical ProductVariant, or return a specific unresolved/ambiguous reason. Matching is deterministic and conservative: missing attributes are not wildcards, and a GTIN never overrides contradictory product metadata.

**Implementation ownership**
- `app.matching.canonical_matching`: canonical database-backed resolver and result types.
- `app.catalog.normalization`: shared identity normalization; matching must not copy normalization rules.
- `app.models`: SQLAlchemy persistence entities.
- `app.services.ingestion_persistence`: persist match decisions and audit evidence.

**Boundaries**
- No retailer network access, discovery, scraping or price refresh.
- No offer publication; the ingestion/persistence service owns that transaction.
- Ambiguous or incomplete identities remain unresolved for review.
- `app.services.canonical_matching` is a temporary compatibility re-export only; new imports use this package.

**Tests:** `backend/tests/test_canonical_matching.py` is the canonical regression suite.

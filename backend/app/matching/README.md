# Matching layer

**Responsibility:** resolve retailer product observations to one canonical ProductVariant, or return a specific unresolved/ambiguous reason. Matching is deterministic and conservative: missing variant attributes are not wildcards, and a GTIN never overrides contradictory product metadata.

**Implementation ownership**
- `app.matching.canonical_matching`: canonical database-backed resolver and result types.
- `app.matching.legacy_fallback`: the single transitional adapter to Next Engine; invoked only after the database-native resolver has no safe match.
- `app.catalog.normalization`: shared identity normalization; matching must not copy normalization rules.
- `app.models`: SQLAlchemy persistence entities.
- `app.offers.persistence`: persists the selected match and audit evidence; matching itself never writes to the database.

**Boundaries**
- No retailer network access, discovery, scraping, offer publication or price refresh.
- A successful database-native match always wins; the legacy matcher cannot override it.
- Ambiguous, incomplete or unmapped legacy IDs remain pending for review.
- `app.services.canonical_matching` is a temporary compatibility re-export only; new imports use this package.

**Tests:** `backend/tests/test_canonical_matching.py` and `backend/tests/test_legacy_matching_fallback.py`.

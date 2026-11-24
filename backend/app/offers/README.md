# Offers

**Responsibility:** stage retailer observations, persist canonical match outcomes, enforce publication eligibility, and create or update verified offers with price-history and match-audit evidence.

**Implementation ownership**
- `app.offers.persistence`: single SQLAlchemy persistence gate for raw staging, canonical/legacy ID resolution, match audit and offer promotion.
- `app.matching.canonical_matching`: decides the canonical variant; offers persists the decision but does not implement matching rules.
- `app.models`: Offer, IngestionRaw, MatchAudit and PriceHistory persistence entities.
- `app.pricing.offer_refresh`: updates already-published offers; it does not rediscover or rematch them.
- `app.services.connector_ingestion`: orchestration across connector parsing, matching, validation and this persistence gate.

**Boundaries**
- No retailer network calls or discovery.
- Publication requires a resolved canonical variant and explicit valid price, currency, availability and absolute HTTP(S) URL.
- Caller owns the database transaction.
- `app.services.ingestion_persistence` is a temporary compatibility re-export only.

**Tests:** `backend/tests/test_canonical_matching.py`, `backend/tests/test_phase2_bplatz_postgres.py`, and the existing `tests/test_bplatz_persistence_service.py`.

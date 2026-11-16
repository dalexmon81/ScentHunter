# Account profiles and delivery destinations

## Product rules

- A guest can search without creating an account. The search request must carry a delivery destination context.
- Registration stores an email, a secure password hash, and the user's residence country. Residence is a default preference, not a permanent shipping destination.
- A user may choose another delivery country and optional postal code for any search (for example, a Luxembourg resident sending a gift to Italy).
- Saved delivery destinations are optional shortcuts. The user may change the destination per search without changing their residence profile.
- Do not collect a full street address or telephone number: ScentHunter compares retailer offers and does not fulfil orders.
- Passwords must never be stored or logged in plaintext. The database stores only a password hash produced by a dedicated password-hashing implementation.

## Schema delivered

- Migration 0014 creates `user_accounts` and `user_delivery_destinations`.
- Migration 0015 creates `user_sessions`; only a SHA-256 digest of each opaque bearer token is persisted.
- A partial unique index guarantees at most one default saved destination per account.
- Residence and delivery destination are deliberately separate. No full street address or phone field is present.

## Search destination resolution

1. Guest request: use the country and optional postal code supplied for this search; if absent, ask for a country before showing delivered-price comparisons.
2. Signed-in request with explicit destination: explicit search destination wins.
3. Signed-in request without explicit destination: use the selected saved default destination, otherwise the account residence country and optional postal code.
4. Never infer shipping eligibility from the user's residence if a different destination was selected.

## Delivered-price rules

- Compare one-product orders first: product offer price plus the retailer's applicable destination shipping rule.
- A verified delivered total is available only when both offer price and shipping fee/threshold are valid and verified for the selected destination and currency.
- Estimated shipping is shown as an estimate and never mixed into confirmed-total ranking.
- Missing, stale, unavailable or currency-mismatched shipping data is never treated as zero/free shipping.
- Free-shipping thresholds apply to the retailer's qualifying order subtotal, not automatically to each individual product in a future multi-item basket. The retailer's terms must establish whether the threshold is before/after discounts and which product categories qualify.
- Multi-product basket optimization is a later phase. It must compare one combined retailer basket against separate purchases and must not be implied by the one-product quote endpoint.

## Implemented on `phase9/staging-catalog-api`

- Account registration, login, logout and profile read endpoints are implemented.
- Passwords are hashed with PBKDF2-HMAC-SHA256 (600,000 iterations); bearer tokens are opaque, expire after 30 days, and are stored only as SHA-256 digests. Logout revokes the session.
- Account API requests reuse a process-scoped SQLAlchemy session factory/connection pool; each HTTP request still receives and closes its own short-lived ORM Session.
- Saved delivery destinations support list, create, set-default and delete operations, with ownership checks.
- Frontend account/profile UI is connected to the API. The bearer token is held in JavaScript memory only; a browser reload therefore requires the user to log in again.
- Guest search requires a delivery country and accepts an optional postal code. The frontend sends both to `GET /search-start`.
- For signed-in users, the profile flow resolves the destination as explicit selection first, saved default second, residence fallback third. An explicit delivery selection is not overwritten.
- Catalog search requests a destination-specific shipping quote for each published offer. Fresh verified quotes carry a delivered total; estimated, stale, unavailable and unknown rates do not.
- Frontend sorting prioritizes verified delivered totals within the same currency and displays product price, shipping fee and delivered total separately.
- No real shipping rates are seeded. Unknown shipping is never presented as free.

## Staging verification completed

The staging deployment and account smoke test passed on 7 November 2026. The workflow verified registration, profile read, saved destination creation/listing, logout revocation, and a search with an explicit delivery country/postal code. The synthetic smoke-test account was removed after the test.

Staging only: `https://scenthunter-staging-workers.fly.dev/`. The changes remain in draft PR #424 and have not been merged or deployed to production.

## Remaining before production or general user release

- Email verification and password reset/recovery.
- Authentication abuse controls, including rate limits and a documented lockout/abuse policy.
- Review and improve browser session persistence. Prefer a Secure, HttpOnly, SameSite cookie with CSRF protection; do not move bearer tokens into localStorage. Until that work is completed, users must log in again after a page reload.
- Full browser-level end-to-end coverage of registration, login, profile, destination selection and search.
- Operational/security review of authentication, session expiry and revocation.
- Populate shipping rates only from sourced evidence, with scope and expiry. No shipping values should be invented or seeded without evidence.
- Verify real offer plus delivered-total display only after a retailer has granted the required written authorization and feed access.

## Explicit non-goals

- Account residence is not treated as the delivery destination when the user explicitly chooses another country.
- ScentHunter does not collect full street addresses or telephone numbers.
- Unknown shipping fees are not assumed to be zero.
- A retailer's presence in CJ, an application marked pending, or a connector in the codebase is not authorization to ingest or publish that retailer's offers.

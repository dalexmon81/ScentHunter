# Account profiles and delivery destinations

## Product rules

- A guest can search without creating an account. The search request must carry a delivery destination context.
- Registration stores an email, a secure password hash, and the user's residence country. Residence is a default preference, not a permanent shipping destination.
- A user may choose another delivery country and optional postal code for any search (for example, a Luxembourg resident sending a gift to Italy).
- Saved delivery destinations are optional shortcuts. The user may change the destination per search without changing their residence profile.
- Do not collect a full street address or telephone number: ScentHunter compares retailer offers and does not fulfil orders.
- Passwords must never be stored or logged in plaintext. The database stores only a password hash produced by a dedicated password-hashing implementation.

## Schema delivered in migration 0014

- `user_accounts`: normalized unique email, password hash, residence ISO country, optional residence postal code, active flag and email verification timestamp.
- `user_delivery_destinations`: user-owned named destination, ISO country, optional postal code and default flag.
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

## Remaining implementation before user-facing release

- Registration, login, logout, password reset, email verification and session/token security.
- Password hashing and verification using a maintained password-hashing library; rate limits and abuse protection.
- Guest/search destination context in the catalog search API and frontend country/postal selector.
- Account profile and saved-destination CRUD endpoints with ownership checks.
- Resolve destination according to the precedence above and pass it into shipping quote/ranking.
- Integration tests for guest search, residence default, destination override, saved destination ownership and delivered-price ordering.
- No real shipping rates should be inserted without source evidence and expiry.


## Implementation status on phase9/staging-catalog-api

Implemented in the current draft PR:
- Migration 0014: account profiles and saved delivery destinations.
- Migration 0015: opaque revocable sessions; only a SHA-256 digest of each bearer token is persisted.
- `POST /account/register`: creates an account; password is hashed with PBKDF2-HMAC-SHA256 (600,000 iterations).
- `POST /account/login`, `POST /account/logout`, `GET /account/me`.
- `GET/POST /account/destinations`, `PUT /account/destinations/{id}/default`, `DELETE /account/destinations/{id}`; destination ownership is enforced.
- Guest search UI now requires a delivery country and accepts an optional postal code. It sends these to `GET /search-start`.
- Catalog search requests a destination-specific shipping quote for each published offer. Fresh verified quotes carry a delivered total; estimated, stale, unavailable and unknown rates do not.
- Frontend sorting prioritizes verified delivered totals within the same currency and displays product price, shipping fee and delivered total separately.

Still required before production or general user release:
- Run the complete PostgreSQL CI workflow and verify Alembic 0015 on isolated Fly staging.
- Add authentication abuse controls (rate limits, account lockout policy, password reset, email verification and operational security review).
- Connect the account UI to the API; currently guest destination selection is integrated, while account registration/login and saved destinations are API-only.
- Add a signed-in search destination resolver: explicit per-search destination first, then saved default destination, then residence country.
- Review whether password hashing parameters should be calibrated against the production runtime and add secure token transport/storage policy in the frontend.
- Populate shipping rates only from sourced evidence and expiry. No shipping values are seeded.
- Verify real offer + delivery-total display with authorized retailer offers before acceptance.

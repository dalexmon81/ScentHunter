# Notino API.SH fallback

ScentHunter can optionally use API.SH as a Notino public-data provider when the authorized CJ feed has no matching offer.

## Configuration

Set `APISH_API_KEY` in the application environment. Do not commit the key, add it to source control, or place it in a workflow file.

The provider is disabled when the variable is absent. ScentHunter then continues to use its bounded direct Notino.fr fallback.

## Request and cost bounds

- One Notino search request per product search.
- Up to three product-detail requests for matching perfume candidates.
- Country is fixed to `fr`, matching the existing Notino.fr connector.
- API.SH documents one credit per endpoint call.
- Product-detail variant prices must be EUR, have a valid Notino.fr product URL, and match the product identity.
- A requested size must match a returned variant size. Ambiguous sizes are not silently substituted.
- API errors do not make a product unavailable; the existing direct fallback remains available.

## Data and attribution

API.SH is an independent third-party provider, not an official Notino API. Returned prices and stock are public storefront data and may change. Affiliate attribution is not supplied by this provider; do not label these URLs as CJ affiliate links.

Documentation: https://api.sh/docs/notino-search and https://api.sh/docs/notino-product.

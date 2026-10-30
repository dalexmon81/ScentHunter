-- Upgrade existing Offer Engine databases to support multiple feed variants
-- that share one parent product URL. External retailer IDs remain unique.
BEGIN;
ALTER TABLE sh_retailer_listings
    DROP CONSTRAINT IF EXISTS sh_retailer_listings_retailer_id_product_url_key;
CREATE INDEX IF NOT EXISTS sh_listing_url_idx
    ON sh_retailer_listings(retailer_id, product_url);
COMMIT;

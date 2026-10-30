-- Additive PostgreSQL 15+ migration. Legacy tables remain untouched.
BEGIN;
CREATE TABLE IF NOT EXISTS sh_products (
 product_id TEXT PRIMARY KEY, brand TEXT NOT NULL, canonical_name TEXT NOT NULL,
 concentration TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(length(trim(brand))>0), CHECK(length(trim(canonical_name))>0)
);
CREATE TABLE IF NOT EXISTS sh_variants (
 variant_id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES sh_products(product_id),
 size_ml INTEGER NOT NULL CHECK(size_ml>0), concentration TEXT, gtin TEXT,
 package_type TEXT NOT NULL DEFAULT 'standard',
 UNIQUE NULLS NOT DISTINCT(product_id,size_ml,concentration,package_type), UNIQUE(variant_id,product_id)
);
CREATE TABLE IF NOT EXISTS sh_retailers (
 retailer_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, market TEXT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE,
 max_offer_age_seconds INTEGER NOT NULL DEFAULT 86400 CHECK(max_offer_age_seconds>0)
);
CREATE TABLE IF NOT EXISTS sh_retailer_listings (
 listing_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 retailer_id TEXT NOT NULL REFERENCES sh_retailers(retailer_id),
 external_id TEXT, product_url TEXT NOT NULL, market TEXT NOT NULL, raw_title TEXT NOT NULL,
 raw_brand TEXT, raw_size_ml INTEGER CHECK(raw_size_ml IS NULL OR raw_size_ml>0),
 raw_concentration TEXT, raw_gtin TEXT, canonical_product_id TEXT, canonical_variant_id TEXT,
 match_status TEXT NOT NULL DEFAULT 'unresolved'
 CHECK(match_status IN ('matched','unresolved','ambiguous','rejected')),
 first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(retailer_id,external_id), UNIQUE(retailer_id,product_url),
 UNIQUE(listing_id,canonical_product_id,canonical_variant_id),
 FOREIGN KEY(canonical_variant_id,canonical_product_id) REFERENCES sh_variants(variant_id,product_id),
 CHECK((match_status='matched')=(canonical_product_id IS NOT NULL AND canonical_variant_id IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS sh_listing_match_idx ON sh_retailer_listings(canonical_variant_id,retailer_id);
CREATE TABLE IF NOT EXISTS sh_offer_observations (
 observation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 listing_id BIGINT NOT NULL REFERENCES sh_retailer_listings(listing_id),
 observed_at TIMESTAMPTZ NOT NULL, price NUMERIC(12,2), currency CHAR(3) NOT NULL,
 availability TEXT NOT NULL CHECK(availability IN ('in_stock','out_of_stock','unknown')),
 source TEXT NOT NULL CHECK(source IN ('feed','api','product_page','manual')),
 verification TEXT NOT NULL CHECK(verification IN ('verified','unverified','rejected')),
 evidence_url TEXT, evidence_hash TEXT, rejection_reason TEXT, raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 UNIQUE(observation_id,listing_id),
 CHECK(price IS NULL OR price>=0),
 CHECK(verification<>'verified' OR (price IS NOT NULL AND availability<>'unknown' AND evidence_url IS NOT NULL AND evidence_hash IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS sh_observation_listing_time_idx ON sh_offer_observations(listing_id,observed_at DESC);
CREATE TABLE IF NOT EXISTS sh_current_offers (
 listing_id BIGINT PRIMARY KEY REFERENCES sh_retailer_listings(listing_id),
 observation_id BIGINT NOT NULL UNIQUE,
 product_id TEXT NOT NULL, variant_id TEXT NOT NULL, verified_at TIMESTAMPTZ NOT NULL,
 FOREIGN KEY(variant_id,product_id) REFERENCES sh_variants(variant_id,product_id),
 FOREIGN KEY(listing_id,product_id,variant_id) REFERENCES sh_retailer_listings(listing_id,canonical_product_id,canonical_variant_id),
 FOREIGN KEY(observation_id,listing_id) REFERENCES sh_offer_observations(observation_id,listing_id)
);
CREATE INDEX IF NOT EXISTS sh_current_variant_idx ON sh_current_offers(product_id,variant_id);
CREATE TABLE IF NOT EXISTS sh_connector_runs (
 run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 retailer_id TEXT NOT NULL REFERENCES sh_retailers(retailer_id), source TEXT NOT NULL,
 started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ,
 status TEXT NOT NULL CHECK(status IN ('running','success','partial','failed')),
 listings_seen INTEGER NOT NULL DEFAULT 0, observations_written INTEGER NOT NULL DEFAULT 0,
 offers_published INTEGER NOT NULL DEFAULT 0, error_summary TEXT
);
COMMIT;

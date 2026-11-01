from sqlalchemy import ForeignKey
from app.models import Base, Brand, Fragrance, ProductVariant, Store, Offer, PriceHistory, MatchAudit, IngestionRun

def test_phase2_declares_all_core_tables():
    assert set(Base.metadata.tables) == {
        "brands", "fragrances", "product_variants", "stores",
        "offers", "price_history", "match_audit", "ingestion_runs",
    }

def test_canonical_identity_is_separate_from_retailer_offers():
    assert "canonical_key" in ProductVariant.__table__.columns
    assert "product_variant_id" in Offer.__table__.columns
    assert Offer.__table__.c.product_variant_id.nullable is True
    assert "external_product_id" not in ProductVariant.__table__.columns

def test_variant_distinguishing_attributes_are_persisted():
    columns = ProductVariant.__table__.columns
    for field in ("concentration", "size_ml", "is_tester", "is_refill", "is_gift_set", "gtin"):
        assert field in columns

def test_prices_use_fixed_precision_and_audit_links_are_foreign_keys():
    assert str(Offer.__table__.c.price.type) == "NUMERIC(12, 2)"
    assert str(PriceHistory.__table__.c.price.type) == "NUMERIC(12, 2)"
    assert any(isinstance(fk, ForeignKey) for fk in MatchAudit.__table__.c.offer_id.foreign_keys)

def test_required_offer_and_catalog_indexes_exist():
    indexes = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert {"ix_product_variants_gtin", "ix_offers_status", "ix_offers_captured_at", "ix_offers_price", "ix_offers_store_external_product"} <= indexes

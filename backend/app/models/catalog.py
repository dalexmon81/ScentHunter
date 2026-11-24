from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    normalized_name: Mapped[str] = mapped_column(String(220), nullable=False, unique=True)
    fragrances: Mapped[list["Fragrance"]] = relationship(back_populates="brand")
    aliases: Mapped[list["BrandAlias"]] = relationship(back_populates="brand", cascade="all, delete-orphan")

class Fragrance(Base):
    __tablename__ = "fragrances"
    __table_args__ = (UniqueConstraint("brand_id", "slug", name="uq_fragrances_brand_slug"), Index("ix_fragrances_name", "name"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    slug: Mapped[str] = mapped_column(String(260), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(40))
    family: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[Brand] = relationship(back_populates="fragrances")
    variants: Mapped[list["ProductVariant"]] = relationship(back_populates="fragrance")
    aliases: Mapped[list["FragranceAlias"]] = relationship(back_populates="fragrance", cascade="all, delete-orphan")

class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("size_ml IS NULL OR size_ml > 0", name="size_ml_positive"),
        CheckConstraint("NOT (is_tester AND is_gift_set)", name="tester_not_gift_set"),
        Index("ix_product_variants_gtin", "gtin"), Index("ix_product_variants_size_ml", "size_ml"), Index("ix_product_variants_concentration", "concentration"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fragrance_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("fragrances.id", ondelete="RESTRICT"), nullable=False, index=True)
    concentration: Mapped[str | None] = mapped_column(String(60))
    size_ml: Mapped[int | None] = mapped_column(Integer)
    is_tester: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_refill: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_gift_set: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_mini: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gtin: Mapped[str | None] = mapped_column(String(14))
    canonical_key: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    fragrance: Mapped[Fragrance] = relationship(back_populates="variants")
    offers: Mapped[list["Offer"]] = relationship(back_populates="product_variant")
    store_products: Mapped[list["StoreProduct"]] = relationship(back_populates="product_variant")
    aliases: Mapped[list["ProductVariantAlias"]] = relationship(back_populates="product_variant", cascade="all, delete-orphan")
    gtins: Mapped[list["ProductVariantGtin"]] = relationship(back_populates="product_variant", cascade="all, delete-orphan")

class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        CheckConstraint("reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 1)", name="reliability_score_range"),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="currency_iso_code"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    reliability_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_connector_error: Mapped[str | None] = mapped_column(Text)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    products: Mapped[list["StoreProduct"]] = relationship(back_populates="store")


class LegacyProductIdMap(Base):
    __tablename__ = "legacy_product_id_map"
    legacy_product_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    fragrance_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("fragrances.id", ondelete="RESTRICT"), nullable=False)


class LegacyVariantIdMap(Base):
    __tablename__ = "legacy_variant_id_map"
    legacy_variant_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False)


class IngestionRaw(Base):
    __tablename__ = "ingestion_raw"
    __table_args__ = (Index("ix_ingestion_raw_store_status", "store_id", "status"), CheckConstraint("status IN ('pending','unmatched','matched','promoted','rejected')", name="ingestion_raw_status"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    external_product_id: Mapped[str | None] = mapped_column(String(240))
    legacy_product_id: Mapped[str | None] = mapped_column(String(80))
    legacy_variant_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"))
    store_product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("store_products.id", ondelete="RESTRICT"), index=True)
    match_method: Mapped[str | None] = mapped_column(String(60))
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_nonnegative"),
        CheckConstraint("shipping_cost IS NULL OR shipping_cost >= 0", name="shipping_cost_nonnegative"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="currency_iso_code"),
        Index("ix_offers_store_external_product", "store_id", "external_product_id", unique=True, sqlite_where=text("external_product_id IS NOT NULL"), postgresql_where=text("external_product_id IS NOT NULL")),
        Index("ix_offers_status", "status"), Index("ix_offers_captured_at", "captured_at"), Index("ix_offers_price", "price"), Index("ix_offers_store_id", "store_id"), Index("ix_offers_product_variant_id", "product_variant_id"), CheckConstraint("status <> 'active' OR (length(trim(url)) > 0 AND availability IS NOT NULL)", name="active_offer_required_fields"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_raw_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ingestion_raw.id", ondelete="RESTRICT"), unique=True)
    store_product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("store_products.id", ondelete="RESTRICT"), index=True)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    # NULL means the retailer item is not yet safely matched to a canonical variant.
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"))
    external_product_id: Mapped[str | None] = mapped_column(String(240))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str | None] = mapped_column(String(40))
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    store: Mapped[Store] = relationship()
    store_product: Mapped["StoreProduct | None"] = relationship(back_populates="offers")
    product_variant: Mapped[ProductVariant | None] = relationship(back_populates="offers")
    price_history: Mapped[list["PriceHistory"]] = relationship(back_populates="offer", cascade="all, delete-orphan")
    match_audits: Mapped[list["MatchAudit"]] = relationship(back_populates="offer", cascade="all, delete-orphan")

class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (CheckConstraint("price >= 0", name="price_nonnegative"), CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="currency_iso_code"), Index("ix_price_history_offer_captured_at", "offer_id", "captured_at"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str | None] = mapped_column(String(40))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    offer: Mapped[Offer] = relationship(back_populates="price_history")

class MatchAudit(Base):
    __tablename__ = "match_audit"
    __table_args__ = (CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"), Index("ix_match_audit_offer_id", "offer_id"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"))
    method: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(160))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer: Mapped[Offer] = relationship(back_populates="match_audits")

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (CheckConstraint("products_discovered >= 0 AND offers_created >= 0 AND offers_updated >= 0 AND offers_rejected >= 0", name="nonnegative_counters"), Index("ix_ingestion_runs_store_started_at", "store_id", "started_at"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", server_default="queued")
    products_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    offers_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    offers_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    offers_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    discovery_runs: Mapped[list["DiscoveryRun"]] = relationship(back_populates="ingestion_run")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(back_populates="ingestion_run")


class BrandAlias(Base):
    __tablename__ = "brand_aliases"
    __table_args__ = (
        UniqueConstraint("brand_id", "normalized_alias", "locale", name="uq_brand_alias_identity"),
        Index("ix_brand_aliases_normalized", "normalized_alias"),
        CheckConstraint("verification_status IN ('pending','verified','rejected','ambiguous','legacy')", name="verification_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False)
    alias_text: Mapped[str] = mapped_column(String(220), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(220), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="und", server_default="und")
    alias_type: Mapped[str] = mapped_column(String(40), nullable=False, default="alternate_name", server_default="alternate_name")
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="manual", server_default="manual")
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    brand: Mapped[Brand] = relationship(back_populates="aliases")


class FragranceAlias(Base):
    __tablename__ = "fragrance_aliases"
    __table_args__ = (
        UniqueConstraint("fragrance_id", "normalized_alias", "locale", name="uq_fragrance_alias_identity"),
        Index("ix_fragrance_aliases_normalized", "normalized_alias"),
        CheckConstraint("verification_status IN ('pending','verified','rejected','ambiguous','legacy')", name="verification_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fragrance_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("fragrances.id", ondelete="CASCADE"), nullable=False)
    alias_text: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(240), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="und", server_default="und")
    alias_type: Mapped[str] = mapped_column(String(40), nullable=False, default="alternate_name", server_default="alternate_name")
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="manual", server_default="manual")
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    fragrance: Mapped[Fragrance] = relationship(back_populates="aliases")


class ProductVariantAlias(Base):
    __tablename__ = "product_variant_aliases"
    __table_args__ = (
        Index("ix_product_variant_aliases_normalized", "normalized_alias"),
        Index("uq_product_variant_aliases_global", "product_variant_id", "normalized_alias", "locale", unique=True, postgresql_where=text("store_id IS NULL"), sqlite_where=text("store_id IS NULL")),
        Index("uq_product_variant_aliases_store", "product_variant_id", "normalized_alias", "locale", "store_id", unique=True, postgresql_where=text("store_id IS NOT NULL"), sqlite_where=text("store_id IS NOT NULL")),
        CheckConstraint("verification_status IN ('pending','verified','rejected','ambiguous','legacy')", name="verification_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False)
    store_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"))
    alias_text: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(320), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="und", server_default="und")
    alias_type: Mapped[str] = mapped_column(String(40), nullable=False, default="retailer_title", server_default="retailer_title")
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="manual", server_default="manual")
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    product_variant: Mapped[ProductVariant] = relationship(back_populates="aliases")
    store: Mapped[Store | None] = relationship()


class ProductVariantGtin(Base):
    __tablename__ = "product_variant_gtins"
    __table_args__ = (
        UniqueConstraint("product_variant_id", "normalized_gtin", name="uq_product_variant_gtin_identity"),
        Index("ix_product_variant_gtins_normalized", "normalized_gtin"),
        Index("uq_product_variant_gtins_verified", "normalized_gtin", unique=True, postgresql_where=text("verification_status = 'verified'"), sqlite_where=text("verification_status = 'verified'")),
        CheckConstraint("normalized_gtin ~ '^(\\\\d{8}|\\\\d{12}|\\\\d{13}|\\\\d{14})$'", name="normalized_gtin_format"),
        CheckConstraint("verification_status IN ('pending','verified','rejected','ambiguous','legacy')", name="verification_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False)
    gtin: Mapped[str] = mapped_column(String(14), nullable=False)
    normalized_gtin: Mapped[str] = mapped_column(String(14), nullable=False)
    market: Mapped[str | None] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    evidence: Mapped[dict | None] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product_variant: Mapped[ProductVariant] = relationship(back_populates="gtins")


class StoreProduct(Base):
    __tablename__ = "store_products"
    __table_args__ = (
        UniqueConstraint("store_id", "external_product_id", name="uq_store_products_external_identity"),
        Index("ix_store_products_status_last_seen", "status", "last_seen_at"),
        Index("ix_store_products_product_variant_id", "product_variant_id"),
        CheckConstraint("status IN ('discovered','active','inactive','unavailable','quarantined','unresolved')", name="status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(240), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    raw_title: Mapped[str | None] = mapped_column(Text)
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="discovered", server_default="discovered")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship(back_populates="products")
    product_variant: Mapped[ProductVariant | None] = relationship(back_populates="store_products")
    offers: Mapped[list["Offer"]] = relationship(back_populates="store_product")
    raw_observations: Mapped[list["IngestionRaw"]] = relationship(back_populates="store_product")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(back_populates="store_product")


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','partial','failed')", name="status"),
        CheckConstraint("pages_scanned >= 0 AND products_seen >= 0 AND products_new >= 0 AND products_existing >= 0", name="nonnegative_counters"),
        Index("ix_discovery_runs_store_started_at", "store_id", "started_at"),
        Index("ix_discovery_runs_ingestion_run_id", "ingestion_run_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="SET NULL"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    query_text: Mapped[str | None] = mapped_column(Text)
    discovery_method: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running", server_default="running")
    pages_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    products_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    products_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    products_existing: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="discovery_runs")
    store: Mapped[Store] = relationship()


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','partial','failed','rejected')", name="status"),
        CheckConstraint("http_status IS NULL OR (http_status >= 100 AND http_status <= 599)", name="http_status_range"),
        Index("ix_extraction_runs_store_started_at", "store_id", "started_at"),
        Index("ix_extraction_runs_store_product_started_at", "store_product_id", "started_at"),
        Index("ix_extraction_runs_ingestion_run_id", "ingestion_run_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="SET NULL"))
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    store_product_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("store_products.id", ondelete="SET NULL"))
    requested_url: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running", server_default="running")
    http_status: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str | None] = mapped_column(String(80))
    response_sha256: Mapped[str | None] = mapped_column(String(64))
    extracted_fields: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="extraction_runs")
    store: Mapped[Store] = relationship()
    store_product: Mapped[StoreProduct | None] = relationship(back_populates="extraction_runs")

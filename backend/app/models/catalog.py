from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import LargeBinary, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid, func, text
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
    size_ml: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    is_tester: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_refill: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_gift_set: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_mini: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gtin: Mapped[str | None] = mapped_column(String(14))
    canonical_key: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    fragrance: Mapped[Fragrance] = relationship(back_populates="variants")
    offers: Mapped[list["Offer"]] = relationship(back_populates="product_variant")

class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        CheckConstraint("reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 1)", name="reliability_score_range"),
        CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="currency_iso_code"),
        CheckConstraint("offer_ttl_minutes IS NULL OR offer_ttl_minutes > 0", name="offer_ttl_positive"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    domain: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    # Publication is blocked until an operator configures an explicit freshness TTL.
    offer_ttl_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", server_default="active")
    reliability_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoreAuthorization(Base):
    """Auditable retailer permission record; no row means collection is denied."""
    __tablename__ = "store_authorizations"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'revoked', 'expired')", name="store_authorization_status"),
        CheckConstraint("collection_method IN ('api', 'feed', 'affiliate_feed', 'manual_url', 'other')", name="store_authorization_method"),
        Index("ix_store_authorizations_store_status", "store_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    collection_method: Mapped[str] = mapped_column(String(24), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    authorization_reference: Mapped[str | None] = mapped_column(String(240))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(160))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    __table_args__ = (
        Index("ix_ingestion_raw_store_status", "store_id", "status"),
        Index(
            "uq_ingestion_raw_live_store_external",
            "store_id", "external_product_id", unique=True,
            sqlite_where=text("external_product_id IS NOT NULL AND status IN ('pending','unmatched','matched')"),
            postgresql_where=text("external_product_id IS NOT NULL AND status IN ('pending','unmatched','matched')"),
        ),
        CheckConstraint("status IN ('pending','unmatched','matched','promoted','rejected')", name="ingestion_raw_status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    external_product_id: Mapped[str | None] = mapped_column(String(240))
    legacy_product_id: Mapped[str | None] = mapped_column(String(80))
    legacy_variant_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"))
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


class IngestionArtifact(Base):
    """Immutable raw source artifact retained for deterministic reprocessing."""
    __tablename__ = "ingestion_artifacts"
    __table_args__ = (
        Index("ix_ingestion_artifacts_store_captured", "store_id", "captured_at"),
        UniqueConstraint("store_id", "sha256", name="uq_ingestion_artifacts_store_sha256"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("ingestion_runs.id", ondelete="SET NULL"))
    artifact_format: Mapped[str] = mapped_column(String(24), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IngestionDeadLetter(Base):
    """Durable record of a Celery task that exhausted its retry policy."""
    __tablename__ = "ingestion_dead_letters"
    __table_args__ = (
        Index("ix_ingestion_dead_letters_status_created", "status", "created_at"),
        UniqueConstraint("task_id", name="uq_ingestion_dead_letters_task_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_name: Mapped[str] = mapped_column(String(240), nullable=False)
    task_id: Mapped[str] = mapped_column(String(80), nullable=False)
    args_repr: Mapped[str] = mapped_column(Text, nullable=False)
    kwargs_repr: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(160))


class CanonicalIdentityReview(Base):
    """Durable, append-once review record for uncertain canonical identities."""
    __tablename__ = "canonical_identity_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'duplicate')",
            name="canonical_identity_review_status",
        ),
        Index("ix_canonical_identity_reviews_status_created", "status", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    canonical_key: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    normalized_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    supplied_gtin: Mapped[str | None] = mapped_column(String(14))
    reason: Mapped[str] = mapped_column(String(160), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(160))
    resolution_notes: Mapped[str | None] = mapped_column(Text)


class StoreShippingRate(Base):
    """Country-specific shipping terms, separate from product offers."""
    __tablename__ = "store_shipping_rates"
    __table_args__ = (
        CheckConstraint("length(country_code) = 2 AND country_code = upper(country_code)", name="shipping_country_iso2"),
        CheckConstraint("currency = upper(currency) AND length(currency) = 3", name="shipping_currency_iso3"),
        CheckConstraint("base_cost IS NULL OR base_cost >= 0", name="shipping_base_cost_nonnegative"),
        CheckConstraint("free_shipping_threshold IS NULL OR free_shipping_threshold >= 0", name="shipping_free_threshold_nonnegative"),
        CheckConstraint("minimum_order_total IS NULL OR minimum_order_total >= 0", name="shipping_min_order_nonnegative"),
        CheckConstraint("maximum_order_total IS NULL OR maximum_order_total >= minimum_order_total", name="shipping_order_range_valid"),
        CheckConstraint("minimum_weight_kg IS NULL OR minimum_weight_kg >= 0", name="shipping_min_weight_nonnegative"),
        CheckConstraint("maximum_weight_kg IS NULL OR maximum_weight_kg >= minimum_weight_kg", name="shipping_weight_range_valid"),
        CheckConstraint("delivery_min_days IS NULL OR delivery_min_days >= 0", name="shipping_delivery_min_nonnegative"),
        CheckConstraint("delivery_max_days IS NULL OR delivery_max_days >= delivery_min_days", name="shipping_delivery_range_valid"),
        CheckConstraint("status IN ('verified', 'estimated', 'unavailable')", name="shipping_rate_status"),
        CheckConstraint("method IN ('official_page', 'api', 'feed', 'manual_confirmation')", name="shipping_rate_method"),
        CheckConstraint("status <> 'verified' OR (base_cost IS NOT NULL AND valid_until IS NOT NULL)", name="verified_shipping_rate_has_cost_and_expiry"),
        Index("ix_store_shipping_rates_destination", "store_id", "country_code", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    postal_code_prefix: Mapped[str | None] = mapped_column(String(24))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    base_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    free_shipping_threshold: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    minimum_order_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    maximum_order_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    minimum_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    maximum_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    delivery_min_days: Mapped[int | None] = mapped_column(Integer)
    delivery_max_days: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="estimated", server_default="estimated")
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(String(240))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

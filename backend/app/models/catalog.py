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
    size_ml: Mapped[int | None] = mapped_column(Integer)
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

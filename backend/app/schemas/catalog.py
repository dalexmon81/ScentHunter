"""Stable Pydantic contracts for the catalog-first public and admin APIs."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class OfferScoreBreakdown(BaseModel):
    price: float
    store_reliability: float
    freshness: float
    availability: float
    match_quality: float
    shipping_transparency: float
    penalties: float


class SearchOffer(BaseModel):
    offer_id: str
    store: str
    country: str | None = None
    price: Decimal
    currency: str
    availability: str | None = None
    url: str
    captured_at: datetime | None = None
    shipping_cost: Decimal | None = None
    score: float
    score_breakdown: OfferScoreBreakdown
    landed_price: str | None = None
    verify_price: bool = False
    warning: str | None = None


class SearchVariant(BaseModel):
    variant_id: str
    canonical_key: str
    concentration: str | None = None
    size_ml: int | None = None
    format: dict[str, bool | None] = Field(default_factory=dict)
    offers: list[SearchOffer] = Field(default_factory=list)
    min_price_by_currency: dict[str, str] = Field(default_factory=dict)
    min_price: str | None = None
    store_count: int = 0
    availability: str


class SearchProduct(BaseModel):
    brand: str
    brand_slug: str
    fragrance: str
    fragrance_slug: str
    family: str | None = None
    gender: str | None = None
    olfactory_notes: list[Any] = Field(default_factory=list)
    variants: list[SearchVariant] = Field(default_factory=list)
    variant_selection_required: bool = False
    offer_count: int = 0


class SearchResponse(BaseModel):
    query: str
    count: int
    offer_count: int
    message: str | None = None
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    limit: int
    offset: int
    results: list[SearchProduct] = Field(default_factory=list)


class ProductVariantRead(BaseModel):
    id: str
    canonical_key: str
    concentration: str | None = None
    size_ml: int | None = None
    format: dict[str, bool | None]


class ProductRead(BaseModel):
    brand: dict[str, str]
    product: dict[str, Any]
    variant_selection_required: bool
    variants: list[ProductVariantRead]


class OfferListRead(BaseModel):
    count: int | None = None
    product_slug: str | None = None
    variant_id: str | None = None
    offers: list[dict[str, Any]]
    message: str | None = None


class ErrorRead(BaseModel):
    detail: str | dict[str, Any]


class AdminStoreRead(BaseModel):
    id: str
    name: str
    slug: str
    status: str
    country: str | None = None
    currency: str
    reliability_score: Decimal | None = None
    last_successful_sync_at: datetime | None = None


class AdminIngestionRunRead(BaseModel):
    id: str
    store_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    products_discovered: int
    offers_created: int
    offers_updated: int
    offers_rejected: int
    errors: list[Any] = Field(default_factory=list)


class AdminMatchingReviewRead(BaseModel):
    id: str
    canonical_key: str
    reason: str
    status: str
    created_at: datetime
    normalized_payload: dict[str, Any]

"""Pure lifecycle rules kept separate from legacy database status columns.

This module is intentionally persistence-free until the additive schema migration
and backfill have been reviewed and tested on isolated staging.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ValidationStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    STALE = "stale"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class LifecycleDecision:
    validation_status: ValidationStatus
    publication_status: PublicationStatus
    reasons: tuple[str, ...] = ()


def evaluate_offer_lifecycle(
    *,
    validation_reasons: tuple[str, ...] = (),
    match_confidence: float | None = None,
    store_active: bool = False,
    evidence_fresh: bool = False,
    purchasable: bool = False,
    explicit_in_stock: bool = False,
    identity_resolved: bool = False,
    operator_quarantined: bool = False,
) -> LifecycleDecision:
    """Fail closed: only complete, validated, fresh evidence can be published."""
    reasons = list(validation_reasons)
    if operator_quarantined:
        return LifecycleDecision(
            ValidationStatus.PENDING, PublicationStatus.QUARANTINED,
            tuple(reasons + ["operator_quarantine"]),
        )
    if not identity_resolved:
        reasons.append("canonical_identity_unresolved")
    if match_confidence is None or not 0.950 <= match_confidence <= 1:
        reasons.append("match_confidence_below_publication_threshold")
    if not store_active:
        reasons.append("store_inactive")
    if not evidence_fresh:
        reasons.append("evidence_stale_or_missing")
    if not purchasable:
        reasons.append("product_not_confirmed_purchasable")
    if not explicit_in_stock:
        reasons.append("availability_not_explicitly_in_stock")
    if reasons:
        return LifecycleDecision(
            ValidationStatus.REJECTED if validation_reasons else ValidationStatus.PENDING,
            PublicationStatus.DRAFT, tuple(dict.fromkeys(reasons)),
        )
    return LifecycleDecision(ValidationStatus.VALIDATED, PublicationStatus.PUBLISHED)

"""Publication gate for fresh verified offer states and positive purchasable prices."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .contracts import Availability, OfferObservation, Verification


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    publish: bool
    reason: str


class OfferPolicy:
    def __init__(self, max_age: timedelta = timedelta(hours=24)):
        if max_age.total_seconds() <= 0:
            raise ValueError("max_age must be positive")
        self.max_age = max_age

    def evaluate(self, observation: OfferObservation, *, now: datetime | None = None) -> PolicyDecision:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if observation.verification is not Verification.VERIFIED:
            return PolicyDecision(False, "not_verified")
        if not observation.product_id or not observation.variant_id:
            return PolicyDecision(False, "identity_not_resolved")
        age = now - observation.observed_at
        if age < timedelta(0):
            return PolicyDecision(False, "observation_from_future")
        if age > self.max_age:
            return PolicyDecision(False, "observation_stale")
        if not observation.evidence_url or not observation.evidence_hash:
            return PolicyDecision(False, "evidence_missing")
        if observation.availability is Availability.UNKNOWN:
            return PolicyDecision(False, "availability_unknown")
        if observation.availability is Availability.OUT_OF_STOCK:
            if observation.price is not None:
                return PolicyDecision(False, "out_of_stock_price_present")
            # A verified sold-out state is useful current availability data,
            # but it is never represented as a purchasable priced offer.
            return PolicyDecision(True, "verified_out_of_stock")
        if observation.price is None:
            return PolicyDecision(False, "price_missing")
        if observation.price <= 0:
            return PolicyDecision(False, "price_not_positive")
        return PolicyDecision(True, "verified_and_fresh")

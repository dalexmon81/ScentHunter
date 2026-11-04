from app.services.offer_lifecycle import (
    PublicationStatus, ValidationStatus, evaluate_offer_lifecycle,
)


def valid_evidence():
    return {
        "match_confidence": 0.995,
        "store_active": True,
        "evidence_fresh": True,
        "purchasable": True,
        "explicit_in_stock": True,
        "identity_resolved": True,
    }


def test_complete_evidence_can_be_published():
    decision = evaluate_offer_lifecycle(**valid_evidence())
    assert decision.validation_status == ValidationStatus.VALIDATED
    assert decision.publication_status == PublicationStatus.PUBLISHED
    assert decision.reasons == ()


def test_missing_or_weak_evidence_fails_closed_to_draft():
    evidence = valid_evidence()
    evidence["match_confidence"] = 0.949
    evidence["explicit_in_stock"] = False
    decision = evaluate_offer_lifecycle(**evidence)
    assert decision.validation_status == ValidationStatus.PENDING
    assert decision.publication_status == PublicationStatus.DRAFT
    assert "match_confidence_below_publication_threshold" in decision.reasons
    assert "availability_not_explicitly_in_stock" in decision.reasons


def test_validation_errors_mark_rejected_without_publication():
    decision = evaluate_offer_lifecycle(
        **valid_evidence(), validation_reasons=("invalid_currency",)
    )
    assert decision.validation_status == ValidationStatus.REJECTED
    assert decision.publication_status == PublicationStatus.DRAFT
    assert decision.reasons == ("invalid_currency",)


def test_operator_quarantine_takes_precedence():
    decision = evaluate_offer_lifecycle(
        **valid_evidence(), operator_quarantined=True
    )
    assert decision.publication_status == PublicationStatus.QUARANTINED
    assert "operator_quarantine" in decision.reasons


def test_unresolved_identity_never_publishes_even_with_high_score():
    evidence = valid_evidence()
    evidence["identity_resolved"] = False
    decision = evaluate_offer_lifecycle(**evidence)
    assert decision.publication_status == PublicationStatus.DRAFT
    assert "canonical_identity_unresolved" in decision.reasons

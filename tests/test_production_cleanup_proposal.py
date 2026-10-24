"""Tests for the production cleanup proposal; no production access is performed."""
from backend.scenthunter_next_engine.production_cleanup_proposal import build_proposal


def test_cleanup_proposal_is_review_only_and_matches_production_audit_counts():
    report = build_proposal()
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["read_only"] is True
    assert report["production_database_mutated"] is False
    assert report["execution_performed"] is False
    assert report["counts_from_source_audit"]["active_deloox_urls_examined"] == 30768
    assert report["counts_from_source_audit"]["invalid_active_urls_found"] == 7
    assert len(report["proposed_url_actions"]) == 7
    assert report["approval_gate"]["production_deactivation_or_quarantine_authorized"] is False
    assert report["approval_gate"]["canonical_merge_authorized"] is False
    assert report["approval_gate"]["migration_authorized"] is False


def test_profondo_identity_collision_is_preserved_for_review_not_merged():
    report = build_proposal()["known_identity_review"]
    assert report["candidate_product_ids"] == ["SH-0043", "SH-AUTO-0019"]
    assert report["SH-0043"]["variant_sizes_ml"] == [75, 125]
    assert report["SH-AUTO-0019"]["variant_sizes_ml"] == [50, 100, 200]
    assert report["production_change_performed"] is False
    assert "defer merge" in report["recommended_disposition"].lower()

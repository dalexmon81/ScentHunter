"""The production Notino bootstrap must stay within the reviewed pilot."""

from pathlib import Path


def test_bootstrap_does_not_enqueue_or_paginate_the_full_notino_feed():
    backend = Path(__file__).resolve().parents[1]
    source = (backend / "scripts" / "bootstrap_notino_postgres.py").read_text()
    assert "enqueue_discovery" not in source
    assert "enqueue_offer_fetch" not in source
    assert "backfill_verified_notino_gtins" in source
    assert "NOTINO_POSTGRES_INGESTION=PASS" in source
    assert "Offer.external_product_id.in_" in source
    assert "valid_until=datetime.now(timezone.utc)" in source


def test_bootstrap_requires_all_four_reviewed_gtins_before_success():
    backend = Path(__file__).resolve().parents[1]
    source = (backend / "scripts" / "bootstrap_notino_postgres.py").read_text()
    assert 'summary.get("promoted_unique_gtins", 0)' in source
    assert "len(VERIFIED_GTINS)" in source
    assert "Targeted Notino Dior Sauvage EDP pilot" in source


def test_bootstrap_commits_only_after_all_four_gtins_are_promoted():
    backend = Path(__file__).resolve().parents[1]
    source = (backend / "scripts" / "bootstrap_notino_postgres.py").read_text()
    promotion = source.index("summary = backfill_verified_notino_gtins(")
    commit = source.index("session.commit()")
    assert promotion < commit
    assert "same outer transaction" in source

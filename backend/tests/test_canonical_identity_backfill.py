from app.services.canonical_identity_backfill import preview_canonical_backfill


def test_backfill_preview_is_dry_run_and_counts_rows():
    preview = preview_canonical_backfill([
        {"id": "a", "brand": "Dior", "title": "Sauvage EDP 100 ml"},
        {"id": "b", "brand": "", "title": "Sauvage EDP 100 ml"},
        {"id": "c", "brand": "Dior", "title": "Sauvage EDP 100 ml",
         "gtin": "4006381333932"},
    ])
    assert preview.ready_count == 1
    assert preview.invalid_count == 1
    assert preview.review_count == 1
    assert len(preview.rows) == 3
    assert preview.rows[0].status == "ready"
    assert preview.rows[1].status == "invalid"
    assert preview.rows[2].reason == "invalid_gtin_requires_review"


def test_backfill_preview_flags_conflicting_gtins_for_same_canonical_key():
    preview = preview_canonical_backfill([
        {"id": "first", "brand": "Dior", "title": "Sauvage EDP 100 ml",
         "gtin": "4006381333931"},
        {"id": "second", "brand": "Christian Dior",
         "title": "Sauvage Eau de Parfum 100 ml", "gtin": "5901234123457"},
    ])
    assert preview.ready_count == 1
    assert preview.review_count == 1
    assert preview.rows[1].reason == "duplicate_canonical_key_gtin_conflict"

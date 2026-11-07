from app.services.offer_deduplication import dedupe_offer_results


def _dedupe(rows, diagnostics=None):
    return dedupe_offer_results(
        rows,
        diagnostics,
        normalize_store=lambda value, default: str(value or default).lower().replace("-", ""),
        safe_float=lambda value: float(value) if value not in (None, "") else None,
        result_identity=lambda item: (
            "url",
            item.get("store"),
            item.get("url"),
        ),
    )


def test_deduplicates_by_primary_identity_and_reports_keeper():
    first = {"store": "other", "url": "/one", "name": "One", "price_num": 12}
    duplicate = {"store": "other", "url": "/one", "name": "One copy", "price_num": 15}
    diagnostics = []

    result = _dedupe([first, duplicate], diagnostics)

    assert result == [first]
    assert diagnostics[0]["action"] == "DROP"
    assert diagnostics[0]["reason"] == "duplicate_dedupe_key"
    assert diagnostics[0]["kept"]["name"] == "One"


def test_easycosmetic_fingerprint_collapses_same_price_but_keeps_other_prices():
    rows = [
        {"store": "easycosmetic", "url": "/a", "name": "A", "price_num": 20},
        {"store": "easycosmetic", "url": "/b", "name": "B", "price_num": 20},
        {"store": "easycosmetic", "url": "/c", "name": "C", "price_num": 21},
    ]

    assert [row["url"] for row in _dedupe(rows)] == ["/a", "/c"]


def test_sabina_fingerprint_preserves_different_variants_and_prices():
    rows = [
        {"store": "sabina", "url": "/a", "name": "Dior Homme", "size_ml": 100, "price_num": 50, "variant_id": "edp"},
        {"store": "sabina", "url": "/b", "name": "Dior Homme", "size_ml": 100, "price_num": 50, "variant_id": "edt"},
        {"store": "sabina", "url": "/c", "name": "Dior Homme", "size_ml": 100, "price_num": 51, "variant_id": "edp"},
        {"store": "sabina", "url": "/d", "name": "Dior Homme", "size_ml": 100, "price_num": 50, "variant_id": "edp"},
    ]

    assert [row["url"] for row in _dedupe(rows)] == ["/a", "/b", "/c"]


def test_non_target_stores_use_only_primary_identity():
    rows = [
        {"store": "other", "url": "/a", "name": "Same", "price_num": 20},
        {"store": "other", "url": "/b", "name": "Same", "price_num": 20},
    ]

    assert _dedupe(rows) == rows

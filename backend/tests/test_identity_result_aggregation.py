from app.services.identity_result_aggregation import aggregate_identity_results


def _aggregate(offers):
    return aggregate_identity_results(
        offers,
        is_non_fragrance_offer=lambda offer: bool(offer.get("non_fragrance")),
        is_concentration_mismatch_offer=lambda offer: bool(offer.get("concentration_mismatch")),
        public_offer=lambda offer: dict(offer),
    )


def test_groups_matched_offers_by_catalog_identity_and_sorts_prices():
    offers = [
        {"_match_status": "matched", "catalog_id": "b", "canonical_name": "Zulu", "brand": "Brand", "price_num": 25},
        {"_match_status": "matched", "catalog_id": "a", "canonical_name": "Alpha", "brand": "Brand", "price_num": 40},
        {"_match_status": "matched", "catalog_id": "b", "canonical_name": "Zulu", "price_num": 10},
    ]

    groups, unresolved = _aggregate(offers)

    assert [group["catalog_id"] for group in groups] == ["a", "b"]
    assert [row["price_num"] for row in groups[1]["offers"]] == [10, 25]
    assert groups[1]["brand"] == "Brand"
    assert unresolved == []


def test_rejects_non_fragrance_and_concentration_mismatch_even_if_matched():
    groups, unresolved = _aggregate([
        {"_match_status": "matched", "catalog_id": "sample", "non_fragrance": True},
        {"_match_status": "matched", "catalog_id": "wrong", "concentration_mismatch": True},
    ])

    assert groups == []
    assert unresolved == []


def test_keeps_unresolved_rows_and_ignores_invalid_or_other_status_rows():
    unresolved_row = {"_match_status": "unresolved", "name": "Unknown"}
    groups, unresolved = _aggregate([
        None,
        "not-an-offer",
        unresolved_row,
        {"_match_status": "rejected", "catalog_id": "rejected"},
        {"_match_status": "matched", "name": "Missing catalog id"},
    ])

    assert groups == []
    assert unresolved == [unresolved_row]
    assert unresolved[0] is not unresolved_row

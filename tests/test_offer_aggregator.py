"""Tests for deterministic, conservative next-engine offer aggregation."""
from decimal import Decimal

from backend.scenthunter_next_engine.models import MatchStatus, OfferMatch, RetailerOffer
from backend.scenthunter_next_engine.offer_aggregator import aggregate_matches


def make_offer(retailer: str, raw_name: str = "Example Fragrance") -> RetailerOffer:
    return RetailerOffer(
        retailer=retailer,
        raw_name=raw_name,
        brand_raw="Example",
        size_ml=100,
        price=Decimal("49.90"),
    )


def test_groups_only_same_canonical_product_and_variant():
    first = OfferMatch(
        offer=make_offer("shop-a"),
        status=MatchStatus.MATCHED,
        canonical_product_id="product-1",
        canonical_variant_id="variant-100",
    )
    second = OfferMatch(
        offer=make_offer("shop-b"),
        status=MatchStatus.MATCHED,
        canonical_product_id="product-1",
        canonical_variant_id="variant-100",
    )
    different_variant = OfferMatch(
        offer=make_offer("shop-c"),
        status=MatchStatus.MATCHED,
        canonical_product_id="product-1",
        canonical_variant_id="variant-50",
    )

    result = aggregate_matches([first, second, different_variant])

    assert result.input_count == 3
    assert result.matched_offer_count == 3
    assert len(result.groups) == 2
    group = next(g for g in result.groups if g.canonical_variant_id == "variant-100")
    assert [offer.retailer for offer in group.offers] == ["shop-a", "shop-b"]


def test_unresolved_and_ambiguous_are_not_grouped():
    unresolved = OfferMatch(
        offer=make_offer("shop-a"),
        status=MatchStatus.UNRESOLVED,
        reason="no_exact_match",
    )
    ambiguous = OfferMatch(
        offer=make_offer("shop-b"),
        status=MatchStatus.AMBIGUOUS,
        reason="multiple_candidates",
        candidate_product_ids=("product-1", "product-2"),
    )

    result = aggregate_matches([unresolved, ambiguous])

    assert result.groups == ()
    assert result.unresolved == (unresolved,)
    assert result.ambiguous == (ambiguous,)
    assert result.matched_offer_count == 0
    assert result.input_count == 2


def test_group_order_is_deterministic_and_offer_order_is_preserved():
    matches = [
        OfferMatch(make_offer("shop-z"), MatchStatus.MATCHED, "product-z", "variant-z"),
        OfferMatch(make_offer("shop-b"), MatchStatus.MATCHED, "product-a", "variant-2"),
        OfferMatch(make_offer("shop-a"), MatchStatus.MATCHED, "product-a", "variant-2"),
        OfferMatch(make_offer("shop-c"), MatchStatus.MATCHED, "product-a", "variant-1"),
    ]

    result = aggregate_matches(matches)

    assert [(g.canonical_product_id, g.canonical_variant_id) for g in result.groups] == [
        ("product-a", "variant-1"),
        ("product-a", "variant-2"),
        ("product-z", "variant-z"),
    ]
    group = next(g for g in result.groups if g.canonical_variant_id == "variant-2")
    assert [offer.retailer for offer in group.offers] == ["shop-b", "shop-a"]


def test_empty_input_returns_empty_result():
    result = aggregate_matches([])
    assert result.groups == ()
    assert result.unresolved == ()
    assert result.ambiguous == ()
    assert result.input_count == 0
    assert result.matched_offer_count == 0

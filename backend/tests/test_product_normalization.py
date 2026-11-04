from app.services.product_normalization import (
    normalize_brand, normalize_product, normalize_gtin, deduplication_decision,
)

def test_brand_aliases_and_unicode():
    assert normalize_brand("Dior") == "christian dior"
    assert normalize_brand("Nishane") == "nishane istanbul"
    assert normalize_brand("  LANCÔME! ") == "lancome"

def test_concentration_and_size_are_separate_identity_fields():
    a = normalize_product("Dior", "Dior Sauvage Eau de Parfum 100 ml")
    b = normalize_product("Christian Dior", "Sauvage EDT 100ml")
    c = normalize_product("Dior", "Sauvage EDP 60 ml")
    assert a.fragrance_name == "sauvage"
    assert a.concentration == "edp" and a.size_ml == 100
    assert len({a.canonical_key, b.canonical_key, c.canonical_key}) == 3

def test_packaging_is_not_collapsed():
    normal = normalize_product("Dior", "Sauvage EDP 100 ml")
    tester = normalize_product("Dior", "Sauvage EDP 100 ml tester")
    refill = normalize_product("Dior", "Sauvage EDP 100 ml refill")
    gift = normalize_product("Dior", "Sauvage EDP 100 ml gift set")
    assert len({normal.canonical_key, tester.canonical_key, refill.canonical_key, gift.canonical_key}) == 4

def test_gtin_check_digit_and_conflict_review():
    assert normalize_gtin("4006381333931") == "4006381333931"
    assert normalize_gtin("4006381333932") is None
    decision, conflict = deduplication_decision(
        left_gtin="4006381333931", right_gtin="4006381333931",
        left_key="a", right_key="b")
    assert decision == "same" and conflict is None
    decision, conflict = deduplication_decision(
        left_gtin="4006381333931", right_gtin="4006381333931",
        left_key="a", right_key="b")
    assert decision == "same"

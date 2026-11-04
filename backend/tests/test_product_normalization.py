from app.services.product_normalization import (
    normalize_brand, normalize_product, normalize_gtin, deduplication_decision,
)


def test_brand_aliases_and_unicode():
    assert normalize_brand("Dior") == "christian dior"
    assert normalize_brand("Christian Dior") == "christian dior"
    assert normalize_brand("Nishane") == "nishane istanbul"
    assert normalize_brand("  LANCÔME! ") == "lancome"


def test_concentration_and_size_are_separate_identity_fields():
    edp = normalize_product("Dior", "Dior Sauvage Eau de Parfum 100 ml")
    edt = normalize_product("Christian Dior", "Sauvage EDT 100ml")
    smaller = normalize_product("Dior", "Sauvage EDP 60 ml")
    assert edp.fragrance_name == "sauvage"
    assert edp.concentration == "edp" and edp.size_ml == 100
    assert len({edp.canonical_key, edt.canonical_key, smaller.canonical_key}) == 3


def test_packaging_is_not_collapsed():
    normal = normalize_product("Dior", "Sauvage EDP 100 ml")
    tester = normalize_product("Dior", "Sauvage EDP 100 ml tester")
    refill = normalize_product("Dior", "Sauvage EDP 100 ml refill")
    gift = normalize_product("Dior", "Sauvage EDP 100 ml gift set")
    mini = normalize_product("Dior", "Sauvage EDP 10 ml mini")
    assert len({normal.canonical_key, tester.canonical_key, refill.canonical_key,
                gift.canonical_key, mini.canonical_key}) == 5
    assert tester.is_tester and refill.is_refill and gift.is_gift_set and mini.is_mini


def test_size_units_and_noise_tokens():
    product = normalize_product("Nishane", "Hacivat Extrait 10 cl vaporisateur")
    assert product.brand == "nishane istanbul"
    assert product.fragrance_name == "hacivat"
    assert product.concentration == "extrait"
    assert product.size_ml == 100


def test_conflicting_attributes_require_review():
    import pytest
    with pytest.raises(ValueError, match="conflicting_concentrations"):
        normalize_product("Dior", "Sauvage EDP EDT 100 ml")
    with pytest.raises(ValueError, match="conflicting_packaging"):
        normalize_product("Dior", "Sauvage EDP tester refill 100 ml")
    with pytest.raises(ValueError, match="conflicting_sizes"):
        normalize_product("Dior", "Sauvage EDP 50 ml 100 ml")


def test_gtin_check_digit_and_deduplication():
    assert normalize_gtin("4006381333931") == "4006381333931"
    assert normalize_gtin("4006381333932") is None
    decision, conflict = deduplication_decision(
        left_gtin="4006381333931", right_gtin="4006381333931",
        left_key="different-a", right_key="different-b")
    assert decision == "same" and conflict is None
    decision, conflict = deduplication_decision(
        left_gtin="4006381333931", right_gtin="4006381333932",
        left_key="same", right_key="same")
    assert decision == "same" and conflict is None
    decision, conflict = deduplication_decision(
        left_gtin="4006381333931", right_gtin="5901234123457",
        left_key="same", right_key="same")
    assert decision == "review" and conflict is not None



def test_gtin_accepts_formatting_but_rejects_embedded_letters():
    assert normalize_gtin("4006 3813 33931") == "4006381333931"
    assert normalize_gtin("4006-3813-33931") == "4006381333931"
    assert normalize_gtin("EAN4006381333931") is None
    assert normalize_gtin("4006381333931X") is None

def test_explicit_connector_packaging_is_part_of_canonical_identity():
    standard = normalize_product(
        "Dior", "Sauvage EDP 100 ml", concentration="edp", size_ml=100,
        packaging="standard",
    )
    tester = normalize_product(
        "Dior", "Sauvage EDP 100 ml", concentration="edp", size_ml=100,
        packaging="tester",
    )
    assert standard.packaging == "standard"
    assert tester.packaging == "tester"
    assert standard.canonical_key != tester.canonical_key


def test_unsupported_explicit_packaging_requires_review():
    import pytest
    with pytest.raises(ValueError, match="unsupported_packaging_requires_review"):
        normalize_product("Dior", "Sauvage EDP 100 ml", packaging="mystery_pack")


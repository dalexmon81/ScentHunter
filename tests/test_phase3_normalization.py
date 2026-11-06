from backend.app.matching.normalization import (
    extract_size_ml, normalize_brand, normalize_concentration, normalize_fragrance,
)


def test_brand_aliases_are_stable():
    assert normalize_brand("Dior") == "christian dior"
    assert normalize_brand("Christian Dior") == "christian dior"
    assert normalize_brand("Nishane") == "nishane istanbul"


def test_concentration_aliases_keep_variant_type():
    assert normalize_concentration("Eau de Parfum") == "edp"
    assert normalize_concentration("EDP Intense") == "edp_intense"
    assert normalize_concentration("Extrait de Parfum") == "extrait"


def test_size_units_are_normalized_to_ml():
    assert extract_size_ml("100 ml") == 100
    assert extract_size_ml("10 cl") == 100
    assert extract_size_ml("0.1 L") == 100
    assert extract_size_ml("3.4 fl oz") == 100
    assert extract_size_ml("unknown") is None


def test_name_cleanup_does_not_merge_distinct_variants():
    edp = normalize_fragrance("Dior", "Sauvage Eau de Parfum 100 ml", size="100 ml")
    edt = normalize_fragrance("Christian Dior", "Sauvage Eau de Toilette 100 ml", size="100 ml")
    assert edp.brand == "christian dior"
    assert edp.name == edt.name == "sauvage"
    assert edp.concentration == "edp"
    assert edt.concentration == "edt"
    assert edp.canonical_key != edt.canonical_key


def test_tester_refill_and_gift_set_are_separate_dimensions():
    standard = normalize_fragrance("Chanel", "Bleu de Chanel Eau de Parfum 100 ml")
    tester = normalize_fragrance("Chanel", "Bleu de Chanel EDP 100 ml Tester")
    refill = normalize_fragrance("Chanel", "Bleu de Chanel EDP 100 ml Refill")
    assert standard.name == tester.name == refill.name == "bleu de chanel"
    assert len({standard.canonical_key, tester.canonical_key, refill.canonical_key}) == 3


def test_gender_marker_is_separate_from_canonical_name():
    item = normalize_fragrance("Prada", "Paradoxe Eau de Parfum Women 90 ml")
    assert item.name == "paradoxe"
    assert item.audience == "women"

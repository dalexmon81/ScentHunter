from app.services.offer_identity import (
    is_dior_line_url_mismatch,
    offer_concentration_token,
)


def test_concentration_parser_prefers_intense_edp_and_edt():
    assert offer_concentration_token("Dior Sauvage Eau de Parfum Intense") == "edp_intense"
    assert offer_concentration_token("Sauvage EDT Intense") == "edt_intense"


def test_concentration_parser_recognizes_standard_concentrations():
    cases = {
        "Eau de Parfum": "edp",
        "EDT 100 ml": "edt",
        "Eau de Cologne": "edc",
        "Extrait de Parfum": "extrait",
        "Parfum": "parfum",
    }
    for value, expected in cases.items():
        assert offer_concentration_token(value) == expected


def test_elixir_wins_over_generic_parfum_url_descriptor():
    assert offer_concentration_token("dior-sauvage-elixir-parfum-60ml") == "elixir"


def test_concentration_parser_handles_empty_and_non_string_values():
    assert offer_concentration_token(None) == ""
    assert offer_concentration_token("") == ""
    assert offer_concentration_token(123) == ""


def test_concentration_parser_does_not_match_partial_words():
    assert offer_concentration_token("EDPextra") == ""
    assert offer_concentration_token("parfumery") == ""


def test_dior_line_guard_rejects_sauvage_title_linked_to_eau_sauvage():
    assert is_dior_line_url_mismatch({
        "name": "Dior Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-eau-sauvage-edt",
    }) is True


def test_dior_line_guard_rejects_eau_sauvage_title_linked_to_sauvage():
    assert is_dior_line_url_mismatch({
        "name": "Dior Eau Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-sauvage-edt",
    }) is True


def test_dior_line_guard_accepts_matching_product_line():
    assert is_dior_line_url_mismatch({
        "name": "Dior Eau Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-eau-sauvage-edt",
    }) is False
    assert is_dior_line_url_mismatch({
        "name": "Dior Sauvage Eau de Toilette",
        "url": "https://shop.example/dior-sauvage-edt",
    }) is False


def test_dior_line_guard_ignores_non_dictionary_values():
    assert is_dior_line_url_mismatch(None) is False
    assert is_dior_line_url_mismatch("Dior Sauvage") is False


def test_concentration_mismatch_guard_rejects_edp_title_linked_to_edt():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer({
        "name": "Dior Sauvage Eau de Parfum",
        "url": "https://shop.example/dior-sauvage-eau-de-toilette",
    }) is True


def test_concentration_mismatch_guard_rejects_known_brand_conflict():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer({
        "name": "French Avenue Chaos",
        "brand": "French Avenue",
        "url": "https://shop.example/vertus-chaos",
    }) is True


def test_concentration_mismatch_guard_accepts_consistent_identity():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer({
        "name": "Dior Sauvage Eau de Parfum",
        "brand": "Dior",
        "url": "https://shop.example/dior-sauvage-eau-de-parfum",
    }) is False


def test_concentration_mismatch_guard_ignores_non_dictionary_values():
    from app.services.offer_identity import is_concentration_mismatch_offer

    assert is_concentration_mismatch_offer(None) is False
    assert is_concentration_mismatch_offer("Dior Sauvage") is False

from app.services.offer_identity import offer_concentration_token


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

from app.services.store_identity import normalize_store_key


def test_normalize_store_key_handles_known_aliases():
    cases = {
        " Bplatz.de ": "bplatz",
        "Parfum City": "parfumcity",
        "parfum zentrum": "parfumzentrum",
        "parfum-zentrum": "parfumzentrum",
        "Perfume Market": "perfumemarket",
        "orioudh.com": "orioudh",
    }
    for source, expected in cases.items():
        assert normalize_store_key(source) == expected


def test_normalize_store_key_uses_fallback_for_empty_values():
    assert normalize_store_key(None, " Deloox ") == "deloox"
    assert normalize_store_key("", None) == ""


def test_normalize_store_key_preserves_unknown_store_keys():
    assert normalize_store_key("New Retailer") == "new retailer"
